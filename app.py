import streamlit as st
from PIL import Image, ImageFilter
import numpy as np
import pytesseract
from streamlit_drawable_canvas import st_canvas
import requests
import json
import base64
import re
import io
import fitz  # PyMuPDF
import pyperclip

st.set_page_config(
    page_title="Document Viewer App",
    page_icon="📊",
    layout="wide"
)

# Configure the path to Tesseract if necessary
pytesseract.pytesseract.tesseract_cmd = r'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'

# Function to load document types from API
def get_document_types():
    url = "https://edms-demo.epik.live/api/v4/document_types/"
    document_types = []
    next_url = url
    while next_url:
        response = requests.get(next_url, auth=('admin', '1234@BCD'))
        if response.status_code == 200:
            data = response.json()
            document_types.extend(data['results'])
            next_url = data['next']
        else:
            return []
    return document_types

# Function to load metadata types from API
def get_metadata_types(doc_type_id):
    url = f"https://edms-demo.epik.live/api/v4/document_types/{doc_type_id}/metadata_types/"
    response = requests.get(url, auth=('admin', '1234@BCD'))
    if response.status_code == 200:
        return response.json()['results']
    else:
        return []

# Function to perform OCR on the selected region
def perform_ocr(image, rect):
    left, top, width, height = rect["left"], rect["top"], rect["width"], rect["height"]
    roi = image[top:top + height, left:left + width]
    text = pytesseract.image_to_string(roi, lang='eng')
    return text.strip()

# Function to load image
def load_image(image_file):
    return Image.open(image_file)

# Function to display PDF and convert to image with navigation
def display_pdf_and_convert_to_image(uploaded_file):
    images = []
    original_sizes = []
    try:
        doc = fitz.open(stream=uploaded_file.getvalue(), filetype="pdf")
        total_pages = len(doc)
        current_page = st.session_state.get('current_page', 0)

        col_empty_PDF, col1_titlePDF, col2, col3, col4 = st.columns([1, 5, 2, 2, 1])
        with col1_titlePDF:
            st.markdown("#### Preview of the PDF:")

        with col2:
            if st.button('Previous page', key='prev_page'):
                if current_page > 0:
                    st.session_state['canvas_reset'] = True  # Flag to reset canvas
                    current_page -= 1
                    st.session_state['current_page'] = current_page

        with col3:
            if st.button('Next page', key='next_page'):
                if current_page < total_pages - 1:
                    st.session_state['canvas_reset'] = True  # Flag to reset canvas
                    current_page += 1
                    st.session_state['current_page'] = current_page

        page = doc.load_page(current_page)
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        img = img.filter(ImageFilter.SHARPEN)
        images.append(img)
        original_sizes.append((pix.width, pix.height))
    except Exception as e:
        st.error(f"Error in PDF processing: {e}")
    return images, original_sizes



# Function to validate input
def validate_input(input_value, pattern):
    if pattern and not re.match(pattern, input_value):
        return False
    return True

# Function to load JSON safely
def safe_load_json(validation_arguments):
    try:
        valid_json = validation_arguments.replace("'", '"')
        valid_json = valid_json.replace("\\", "\\\\")
        data = json.loads(valid_json)
        pattern = data['pattern']
        cleaned_pattern = pattern.replace('\\\\', '\\')
        return cleaned_pattern      
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return ""
    except KeyError as e:
        print(f"Missing key in JSON data: {e}")
        return ""

# Function to save data to JSON
def save_to_json(file_base64, file_name, doc_type_id, metadata_values):
    metadata_list = [{"id": id, "value": value} for id, value in metadata_values.items()]
    data = {
        "file_base64": file_base64,
        "dms_domain": "edms-demo.epik.live",
        "file_name": file_name,
        "doctype_id": doc_type_id,
        "docmeta_data": metadata_list,
    }
    with open('data.json', 'w') as json_file:
        json.dump(data, json_file)

# Function to save and download data as JSON
def save_and_download_json(file_base64, file_name, doc_type_id, metadata_values):
    progress_text = st.markdown(" ***Please wait a moment for the data submission process.***")
    progress_bar = st.progress(0)
    save_to_json(file_base64, file_name, doc_type_id, metadata_values)
    
    progress_bar.progress(40)
    with open('data.json', 'rb') as f:
        data = f.read()
    progress_bar.progress(75)
    st.download_button(label="Download JSON", data=data, file_name="data.json", mime="application/json")
    json_data = json.loads(data)
    
    response = send_data_to_api(json_data)
    if response.status_code == 200:
        progress_bar.progress(100)
        progress_text.markdown(" :green[Data submission completed successfully!]")
    else:
        st.error(f"Failed to send data to the API: {response.status_code}")
        progress_bar.progress(0)

# Function to send data to API
def send_data_to_api(json_data):
    url = "https://dms.api.epik.live/api/processBase64File"
    headers = {'Content-Type': 'application/json'}
    response = requests.post(url, json=json_data, headers=headers)
    return response

# Function to handle submission
def handle_submission(uploaded_file, doc_type_id, metadata_values):
    metadata_types = get_metadata_types(doc_type_id)
    valid = True
    error_messages = []

    for meta_id, value in metadata_values.items():
        meta_info = next((m for m in metadata_types if m['metadata_type']['id'] == meta_id), None)
        if not meta_info:
            continue

        is_required = meta_info['required']
        validation_info = meta_info['metadata_type'].get('validation_arguments', '')
        pattern = safe_load_json(validation_info) if validation_info else ""

        if is_required and not value.strip():
            error_messages.append(f"Field '{meta_info['metadata_type']['label']}' is required.")
            valid = False
        elif pattern and not validate_input(value, pattern):
            error_messages.append(f"Validation failed for {meta_info['metadata_type']['label']}: {value}")
            valid = False

    if error_messages:
        for msg in error_messages:
            st.error(msg)
    
    if valid:
        file_base64 = base64.b64encode(uploaded_file.getvalue()).decode('utf-8')
        file_name = uploaded_file.name
        save_and_download_json(file_base64, file_name, doc_type_id, metadata_values)
        st.success("Data saved and submitted successfully!")

def main():
    st.markdown("""<style>
        .reportview-container .main .block-container
        {max-width: 90%;}
        </style>""", unsafe_allow_html=True)

    if 'canvas_state' not in st.session_state:
        st.session_state['canvas_state'] = {}

    if 'current_page' not in st.session_state:
        st.session_state['current_page'] = 0

    document_types = get_document_types()
    doc_type_options = {doc['label']: doc['id'] for doc in document_types}

    col_title1, col_title2 = st.columns([1, 8])
    with col_title2:
        st.title('Document Viewer App')

    col_empty_1, col_select, col_upload, col_empty_4 = st.columns([1, 4, 4, 1])
    with col_select:
        doc_type = st.selectbox("Choose the document type:", list(doc_type_options.keys()), key='doc_type')
    with col_upload:
        uploaded_file = st.file_uploader("Upload your document", type=['png', 'jpg', 'jpeg', 'pdf'], key="uploaded_file")

    if uploaded_file:
        file_key = uploaded_file.name + str(uploaded_file.size)

    col1, col2_emt, col3_input_filed = st.columns([6.5, 0.1, 3.4])
    with col1:
        if uploaded_file:
            images = []
            original_sizes = []
            is_pdf = False

            if uploaded_file.type == "application/pdf":
                images, original_sizes = display_pdf_and_convert_to_image(uploaded_file)
                is_pdf = True
            else:
                img = load_image(uploaded_file)
                images.append(img)
                original_sizes.append(img.size)

            for img, original_size in zip(images, original_sizes):
                img_cv = np.array(img.convert('RGB'))

                if is_pdf:
                    # Scale down the image by a factor of 3 if it's a PDF
                    scale_factor = 3
                    new_width = original_size[0] // scale_factor
                    new_height = original_size[1] // scale_factor
                    img_resized = img.resize((new_width, new_height))
                else:
                    # Fit the image within a specific area (max width 800, max height 600)
                    max_width = 1500
                    max_height = 1500
                    img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                    img_resized = img
                    new_width, new_height = img_resized.size
                    scale_factor = original_size[0] / new_width 

                if 'inputs' not in st.session_state:
                    st.session_state.inputs = {}

                if 'new_rect' not in st.session_state:
                    st.session_state.new_rect = False

                if 'fill_data' not in st.session_state:
                    st.session_state.fill_data = False

                metadata_types = get_metadata_types(doc_type_options[doc_type])
                metadata_values = {}
                error_placeholders = {}

                # Create a placeholder for the success message
                success_placeholder = st.empty()

                # Load the canvas state if it exists for the current page
                canvas_state = st.session_state['canvas_state'].get(st.session_state.get('current_page', 0), {})

                canvas_result = st_canvas(
                    fill_color="rgba(255, 0, 0, 0.3)",  # Rectangle color
                    stroke_width=2,
                    stroke_color="rgba(255, 0, 0, 1)",
                    background_image=Image.fromarray(np.array(img_resized)),
                    update_streamlit=True,
                    height=new_height,
                    width=new_width,
                    drawing_mode="rect",
                    key="canvas",
                    initial_drawing=None if st.session_state.get('canvas_reset', False) else canvas_state.get('initial_drawing', {}),
                )

                # Reset the canvas reset flag
                if st.session_state.get('canvas_reset', False):
                    st.session_state['canvas_reset'] = False

                if 'interaction_processed' not in st.session_state:
                    st.session_state.interaction_processed = False

                if canvas_result.json_data is not None:
                    objects = canvas_result.json_data["objects"]
                    if objects:
                        obj = objects[-1]
                        left = int(obj["left"] * scale_factor)
                        top = int(obj["top"] * scale_factor)
                        width = int(obj["width"] * scale_factor)
                        height = int(obj["height"] * scale_factor)

                        roi = img_cv[top:top + height, left:left + width]
                        text = pytesseract.image_to_string(roi, lang='eng').strip()

                        # Copy extracted text to clipboard
                        pyperclip.copy(text)
                        # Display success message above the metadata inputs
                        success_placeholder.success(f"Extracted text copied to clipboard: {text}")

                        # Store the updated canvas state
                        st.session_state['canvas_state'][st.session_state['current_page']] = canvas_result.json_data

                # Add a download button for the image
                img_bytes = io.BytesIO()
                img_resized.save(img_bytes, format='PNG')
                img_bytes = img_bytes.getvalue()

                st.download_button(
                    label="Download Image",
                    data=img_bytes,
                    file_name="extracted_image.png",
                    mime="image/png"
                )

                with col3_input_filed:
                    for meta in metadata_types:
                        metadata_info = meta['metadata_type']
                        label = metadata_info['label']
                        required = meta.get('required', False)
                        input_key = f"meta_{metadata_info['id']}_{uploaded_file.name}"
                        validation = metadata_info.get('validation', '')
                        validation_arguments = metadata_info.get('validation_arguments', '')
                        pattern = safe_load_json(validation_arguments) if 'RegularExpressionValidator' in validation and validation_arguments else ""

                        if metadata_info.get('lookup'):
                            options = metadata_info['lookup'].split(',')
                            selected_option = st.selectbox(
                                f"{label}{' *' if required else ''}", options, key=input_key
                            )
                            metadata_values[metadata_info['id']] = selected_option
                        else:
                            if input_key not in st.session_state.inputs:
                                st.session_state.inputs[input_key] = ""
                            user_input = st.text_input(
                                f"{label}{' *' if required else ''}",
                                st.session_state.inputs[input_key],
                                key=input_key
                            )
                            error_placeholders[metadata_info['id']] = st.empty()
                            metadata_values[metadata_info['id']] = user_input

                            if user_input and pattern and not validate_input(user_input, pattern):
                                error_placeholders[metadata_info['id']].error(f"Invalid input for {label}. Please match the required format.")
                            else:
                                error_placeholders[metadata_info['id']].empty()

                    if st.button("Done and Submit", type="primary"):
                        handle_submission(uploaded_file, doc_type_options[doc_type], metadata_values)

if __name__ == "__main__":
    main()
