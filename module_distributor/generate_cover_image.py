"""
generate_cover_image.py
Generates a topic-relevant cover image for a blog article using
the Google Gemini (Imagen) API. The image is saved to a temporary
file and its path is returned for upload to Medium.
"""
import os
import base64
import tempfile

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def generate_cover_image(title: str, categories: list = None) -> str:
    """
    Generate a cover image for the given article title and categories
    using Gemini's image generation capabilities.

    Returns the absolute path to the generated image file (JPEG),
    or "" if generation fails or API key is not configured.
    """
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set. Skipping cover image generation.")
        return ""

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)

        # Build a descriptive prompt for a professional tech blog cover image
        tags = ", ".join(categories[:5]) if categories else "technology, infrastructure"
        prompt = (
            f"Create a professional, modern cover image for a technical blog article titled: "
            f'"{title}". '
            f"Related topics: {tags}. "
            f"Style: Clean, minimalist tech illustration with a dark background. "
            f"Use abstract geometric shapes, subtle gradients, and glowing accent colors "
            f"(electric blue, cyan, or purple). "
            f"The image should feel premium and editorial — suitable for a Medium.com article header. "
            f"NO text, NO words, NO letters, NO watermarks in the image. "
            f"Aspect ratio: wide/landscape (16:9). "
            f"High quality, 4K resolution feel."
        )

        print(f"Generating cover image with Gemini...")

        # Use generate_content with image generation model
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

        # Extract image from response parts
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                    # Save the image to a temporary file
                    ext = "png" if "png" in part.inline_data.mime_type else "jpeg"
                    img_path = os.path.join(
                        tempfile.gettempdir(), f"medium_cover_{os.getpid()}.{ext}"
                    )
                    with open(img_path, "wb") as f:
                        f.write(part.inline_data.data)
                    print(f"Cover image generated and saved to: {img_path}")
                    return img_path

        print("Warning: Gemini response did not contain an image.")
        return ""

    except Exception as exc:
        print(f"Failed to generate cover image via Gemini: {exc}")
        return ""
