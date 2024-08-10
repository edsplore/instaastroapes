import os
import json
import random
import cv2
from flask import Flask, jsonify, request
from PIL import Image
import openai
import ffmpeg
import subprocess
import shutil
import requests

app = Flask(__name__)

# Configuration
BASE_DIR = "instagram_posts"
LOGO_PATH = "logos/astroapes-logo-nobg.png"  # Replace with the path to your logo
OPENAI_API_KEY = "sk-proj-P1QAgK8Nk5uk9yTqipXwT3BlbkFJgWH4VPrNhSzk7J5IIXTk"  # Replace with your actual OpenAI API key

openai.api_key = OPENAI_API_KEY

def get_random_post():
    accounts = os.listdir(BASE_DIR)
    account = random.choice(accounts)
    posts = os.listdir(os.path.join(BASE_DIR, account))
    post = random.choice(posts)
    return account, post

def add_logo_to_image(image_path, logo_path, output_path):
    try:
        with Image.open(image_path) as img, Image.open(logo_path) as logo:
            logo = logo.resize((200, 200))  # Increased size to 200x200
            position = (img.width - logo.width - 10, 10)  # Top right corner
            img.paste(logo, position, logo)
            img.save(output_path)
        return output_path
    except Exception as e:
        print(f"Error processing image {image_path}: {str(e)}")
        return None

def get_video_dimensions(video_path):
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
           '-count_packets', '-show_entries', 'stream=width,height',
           '-of', 'csv=p=0', video_path]
    output = subprocess.check_output(cmd).decode('utf-8').strip().split(',')
    return int(output[0]), int(output[1])

def add_logo_to_video(video_path, logo_path, output_path):
    try:
        # Get video dimensions
        width, height = get_video_dimensions(video_path)

        # Calculate logo position (top right corner)
        x = width - 210  # Adjusted for larger logo
        y = 10  # 10 pixels from top edge

        # FFmpeg command to add logo
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output files without asking
            '-i', video_path,
            '-i', logo_path,
            '-filter_complex', f'[1:v]scale=200:200[logo];[0:v][logo]overlay={x}:{y}',  # Increased logo size to 200x200
            '-c:v', 'libx264',  # Use H.264 codec
            '-preset', 'slow',  # Use a slower preset for better compression
            '-crf', '18',       # Constant Rate Factor: 18 is visually lossless
            '-c:a', 'copy',     # Copy audio without re-encoding
            output_path
        ]

        # Run FFmpeg command
        subprocess.run(cmd, check=True)
        
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error processing video {video_path}: {e}")
        return None
    except Exception as e:
        print(f"Error processing video {video_path}: {str(e)}")
        return None
    
def send_text_to_ai(prompt):
    """Send text to AI model for analysis based on the given prompt."""
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    try:
        messages = []
        # Append the new user message to the messages list
        messages.append({"role": "user", "content": prompt})

        # Create a chat completion using the updated message list
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.8,
            max_tokens=1000
        )

        # Extract the response content
        response_content = response.choices[0].message.content
        return response_content
    except Exception as e:
        print(f"Error in AI processing: {e}")
        return None

def generate_new_caption(original_caption, username):
    prompt = f"Based on this Instagram caption: '{original_caption}', write a new engaging caption that keeps the essence of the original but is unique. Include credit to @{username} at the end."
    return send_text_to_ai(prompt)

def delete_user_folder(account):
    user_dir = os.path.join(BASE_DIR, account)
    try:
        shutil.rmtree(user_dir)
        print(f"Successfully deleted entire folder for user: {user_dir}")
    except Exception as e:
        print(f"Error deleting user folder {user_dir}: {str(e)}")

def upload_to_tmpfiles(file_path):
    with open(file_path, 'rb') as file:
        response = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': file})
    if response.status_code == 200:
        url = response.json()['data']['url']
        # Modify the URL to include '/dl/'
        parts = url.split('/')
        parts.insert(-2, 'dl')
        return '/'.join(parts)
    return None

@app.route('/get_random_post', methods=['GET'])
def process_random_post():
    try:
        account, post = get_random_post()
        post_dir = os.path.join(BASE_DIR, account, post)
        
        # Load metadata
        metadata_files = [f for f in os.listdir(post_dir) if f.endswith('_metadata.json')]
        if not metadata_files:
            return jsonify({"error": "Metadata file not found"}), 404
        
        with open(os.path.join(post_dir, metadata_files[0]), 'r') as f:
            metadata = json.load(f)
        
        # Process media
        media_files = sorted([f for f in os.listdir(post_dir) if f.endswith(('.jpg', '.jpeg', '.mp4'))])
        processed_media = []
        for index, media_file in enumerate(media_files, start=1):
            input_path = os.path.join(post_dir, media_file)
            output_path = os.path.join(post_dir, f"processed_{index:02d}_{media_file}")
            if media_file.lower().endswith(('.jpg', '.jpeg')):
                result = add_logo_to_image(input_path, LOGO_PATH, output_path)
            elif media_file.endswith('.mp4'):
                result = add_logo_to_video(input_path, LOGO_PATH, output_path)
            
            if result:
                upload_url = upload_to_tmpfiles(result)
                if upload_url:
                    processed_media.append(upload_url)
                else:
                    processed_media.append(f"Failed to upload: {result}")
            else:
                processed_media.append(f"Failed to process: {input_path}")
        
        # Generate new caption
        new_caption = generate_new_caption(metadata['caption'], metadata['username'])
        if new_caption is None:
            new_caption = "Failed to generate new caption. " + metadata['caption']
        
        response = {
            'original_post': metadata,
            'processed_media': processed_media,
            'new_caption': new_caption
        }
        
        # Delete the entire user folder after processing
        delete_user_folder(account)
        
        return jsonify(response)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)