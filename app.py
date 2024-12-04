from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import os
import subprocess
import shutil
import threading
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
# Load environment variables
ECR_REGISTRY = os.getenv('ECR_REGISTRY')
AWS_REGION = os.getenv('AWS_REGION')
GIT_USERNAME = os.getenv('GIT_USERNAME')
GIT_TOKEN = os.getenv('GIT_TOKEN')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/build', methods=['POST'])
def build_and_push():
    repo_url = request.form.get('repo_url')
    branch_name = request.form.get('branch_name', 'main')

    if not repo_url:
        return jsonify({'status': 'error', 'message': 'Repo URL is required'}), 400

    # Start a background thread to handle the build process
    thread = threading.Thread(target=process_build, args=(repo_url, branch_name))
    thread.start()
    return jsonify({'status': 'success', 'message': 'Build process started'})

def process_build(repo_url, branch_name):
    try:
        repo_dir, commit_hash = clone_repo(repo_url, branch_name)

        # Use the commit hash directly as the image tag
        image_tag = f'{commit_hash}'

        build_docker_image(repo_dir, image_tag)
        push_to_ecr(image_tag)
        
        # Emit final status including image tag
        socketio.emit('status', {'stage': 'all', 'status': 'Build and push completed', 'image_tag': image_tag})
    except subprocess.CalledProcessError as e:
        socketio.emit('status', {'stage': 'all', 'status': f'Error: {str(e)}'})
    finally:
        shutil.rmtree('/app/repo', ignore_errors=True)

def clone_repo(repo_url, branch_name):
    repo_dir = '/app/repo'
    try:
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir)
        socketio.emit('status', {'stage': 'clone', 'status': 'In progress'})
        
        # Insert credentials into the repo URL
        repo_url_with_auth = insert_git_credentials(repo_url)
        
        subprocess.run(['git', 'clone', repo_url_with_auth, repo_dir], check=True)
        socketio.emit('status', {'stage': 'clone', 'status': 'Complete'})
        subprocess.run(['git', '-C', repo_dir, 'checkout', branch_name], check=True)
        socketio.emit('status', {'stage': 'clone', 'status': 'Branch checked out'})
        
        # Get the first four characters of the latest commit hash
        result = subprocess.run(['git', '-C', repo_dir, 'rev-parse', '--short=4', 'HEAD'], check=True, capture_output=True, text=True)
        commit_hash = result.stdout.strip()

    except subprocess.CalledProcessError as e:
        socketio.emit('status', {'stage': 'clone', 'status': f'Error: {e}'})
        raise e
    
    return repo_dir, commit_hash

def insert_git_credentials(repo_url):
    if not GIT_USERNAME or not GIT_TOKEN:
        return repo_url  # Return original URL if credentials are not set
    
    parsed_url = urlparse(repo_url)
    netloc = f"{GIT_USERNAME}:{GIT_TOKEN}@{parsed_url.netloc}"
    return urlunparse(parsed_url._replace(netloc=netloc))

def build_docker_image(repo_dir, image_tag):
    dockerfile_path = os.path.join(repo_dir, 'Dockerfile')
    socketio.emit('status', {'stage': 'build', 'status': 'In progress'})
    subprocess.run(['docker', 'build', '-t', image_tag, '-f', dockerfile_path, repo_dir], check=True)
    socketio.emit('status', {'stage': 'build', 'status': 'Complete'})
    return image_tag

def push_to_ecr(image_tag):
    # AWS ECR login command
    ecr_login_cmd = ['aws', 'ecr', 'get-login-password', '--region', AWS_REGION]
    docker_login_cmd = ['docker', 'login', '--username', 'AWS', '--password-stdin', ECR_REGISTRY]

    # Get ECR password
    ecr_password = subprocess.check_output(ecr_login_cmd).decode('utf-8').strip()
    subprocess.run(docker_login_cmd, input=ecr_password, text=True, check=True)

    # Correctly format the ECR image tag
    ecr_image_tag = f'{ECR_REGISTRY}:{image_tag}'

    # Push Docker image to ECR
    socketio.emit('status', {'stage': 'push', 'status': 'In progress'})
    subprocess.run(['docker', 'tag', image_tag, ecr_image_tag], check=True)
    subprocess.run(['docker', 'push', ecr_image_tag], check=True)
    socketio.emit('status', {'stage': 'push', 'status': 'Complete'})
    print("Image pushed to ECR")

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0')
