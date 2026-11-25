from typing import Optional, Tuple, Union
import gradio as gr
from PIL import Image
import io
import os
import requests


API_URL = os.getenv("API_URL", "http://localhost:5000")
UI_PORT = int(os.getenv("UI_PORT", "7860"))


def find_similar_cats(image):
    if image is None:
        return None, "No image provided"

    img_bytes = io.BytesIO()
    image.convert("RGB").save(img_bytes, format="JPEG")
    img_bytes.seek(0)

    files = {"image": ("image.jpg", img_bytes, "image/jpeg")}

    try:
        response = requests.post(f"{API_URL}/similar", files=files)
    except Exception as e:
        return None, f"Connection error: {str(e)}"

    if response.status_code != 200:
        return None, f"Error: {response.status_code} {response.text}"

    data = response.json()
    similar = data.get("similar", [])

    if not similar:
        return None, "No similar cats found"

    result_images = []
    result_text = "Found similar cats:\n\n"

    for i, item in enumerate(similar, start=1):
        result_text += f"{i}. Distance: {item['distance']:.4f}\n"

        try:
            img_url = item["url"]
            img_response = requests.get(img_url)
            if img_response.status_code == 200:
                img = Image.open(io.BytesIO(img_response.content))
                result_images.append(img)
            else:
                result_text += f"   Failed to load: HTTP {img_response.status_code}\n"
        except Exception as e:
            result_text += f"   Failed to load image: {str(e)}\n"

    return result_images, result_text


def upload_cat(image):
    if image is None:
        return "No image provided"

    img_bytes = io.BytesIO()
    image.convert("RGB").save(img_bytes, format="JPEG")
    img_bytes.seek(0)

    files = {"image": ("image.jpg", img_bytes, "image/jpeg")}

    try:
        response = requests.post(f"{API_URL}/upload", files=files)
    except Exception as e:
        return f"Connection error: {str(e)}"

    if response.status_code != 200:
        return f"Error: {response.status_code} {response.text}"

    data = response.json()
    return f"Uploaded successfully\nID: {data['id']}\nURL: {data['url']}"


if __name__ == "__main__":
    with gr.Blocks(title="Cat Similarity Search") as demo:
        gr.Markdown("# Cat Similarity Search Service")
        gr.Markdown("Upload a cat image to find similar cats or add new cats to the database")

        with gr.Tab("Find Similar Cats"):
            gr.Markdown("### Upload a cat image to find similar ones")
            with gr.Row():
                with gr.Column():
                    search_image = gr.Image(type="pil", label="Upload Cat Image")
                    search_button = gr.Button("Find Similar Cats", variant="primary")
                with gr.Column():
                    search_output_text = gr.Textbox(label="Results", lines=8)

            search_output_gallery = gr.Gallery(label="Similar Cats", columns=5, height="auto")

            search_button.click(
                fn=find_similar_cats,
                inputs=search_image,
                outputs=[search_output_gallery, search_output_text]
            )

        with gr.Tab("Upload New Cat"):
            gr.Markdown("### Add a new cat to the database")
            with gr.Row():
                with gr.Column():
                    upload_image = gr.Image(type="pil", label="Upload Cat Image")
                    upload_button = gr.Button("Upload Cat", variant="primary")
                with gr.Column():
                    upload_output = gr.Textbox(label="Status", lines=5)

            upload_button.click(
                fn=upload_cat,
                inputs=upload_image,
                outputs=upload_output
            )

    demo.launch(server_name="0.0.0.0", server_port=UI_PORT)
