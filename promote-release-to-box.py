import os
import sys
import json
import yaml
import argparse
import requests
import logging
import subprocess
from tqdm import tqdm
from boxsdk import OAuth2,Client
from artifactory import ArtifactoryPath
from requests.auth import HTTPBasicAuth
from boxsdk.exception import BoxAPIException


logging.basicConfig(
     level=logging.WARNING, 
     format= '[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s',
     datefmt='%H:%M:%S'
 )

def get_artifact_info_json(build_name, build_number, rt_auth = (None, None), rt_base_url = None):
    ''' 
    Expected Jfrog CLI is availble in the system.
    Executes these:
    1. jf config add orl-artifactory --interactive=false \
        --enc-password=false --basic-auth-only \
        --artifactory-url https://repo.orl.eng.hitachivantara.com/artifactory \
        --password --user buildguy

    2. jf rt search --server-id orl-artifactory \
        --props "build.name=pdi-xxx-9.5.1.0;build.number=86" "*-9.5.1.0-86.zip" \
        > builds.json

    Alternative way: Use ArtifactoryBuildManager https://github.com/devopshq/artifactory#builds
    
    ^^^^^^^^^^^^^
    from artifactory import ArtifactoryBuildManager

    arti_build = ArtifactoryBuildManager(
        orl_url, auth=auth_orl)

    # Get all builds,space turns into %
    all_builds = arti_build.builds
    print(all_builds)
    ^^^^^^^^^^^^^

    '''
    

    # Define the command and arguments
    command = [
        'jf', 'config', 'add', 'orl-artifactory',
        '--interactive=false', '--enc-password=false', '--basic-auth-only',
        '--artifactory-url', f'{rt_base_url}',
        '--password', f'{rt_auth[0]}',
        '--user', f'{rt_auth[1]}'
    ]

    # Execute the command
    subprocess.run(command)
    
    # Define the command and arguments
    command = ['jf', 'rt', 'search', '--server-id', 'orl-artifactory', '--props', 
               f'build.name={build_name};build.number={build_number}',
               f'*' ]
               # f'{artifact_name}']
    
    output_file = 'artifacts.json'

    # Execute the command and capture the output
    result = subprocess.run(command, capture_output=True, text=True)

    # Parse the command output as JSON
    output_json = json.loads(result.stdout)

    # Save the JSON object to a file
    with open(output_file, 'w') as file:
        json.dump(output_json, file, indent=4)
    
    return output_json, set([artifact['path'].split('/')[-1] for artifact in output_json])


def download_artifacts_v3(artifacts_to_release, builds_output_json, auth=(None, None), rt_base_url = None):

    release_artifact_downloaded = []
    for build_artifact in tqdm(builds_output_json):
        file_name = build_artifact['path']
        if build_artifact['path'].split('/')[-1] in artifacts_to_release.keys():

            logging.info(f"Downloading {file_name}")

            path = build_artifact['path']
            sha1 = build_artifact['sha1']
            sha256 = build_artifact['sha256']
            md5 = build_artifact['md5']

            file_name = build_artifact['path'].split('/')[-1]
            check_sum_file_name = path.split('/')[-1]+'.sum'

            # download artifact
            rt_path = ArtifactoryPath(
                f"{rt_base_url}/"+path, auth=auth, auth_type=HTTPBasicAuth
            )
            
            if not os.path.exists(file_name):
                logging.info(f'Downloading {file_name} from {rt_path}.')
                rt_path.writeto(out=file_name, progress_func=None)
                logging.info(f'Download complete.')
            
            if not os.path.exists(check_sum_file_name):
                logging.info(f'Saving check sum file {check_sum_file_name}')
                with open(check_sum_file_name, 'w') as f:
                    f.write('sha1='+ sha1 +'\n')
                    f.write('sha256='+ sha256 +'\n')
                    f.write('md5='+ md5+'\n')
                
        release_artifact_downloaded.append(file_name)
                
    logging.info(f'Release artifacts {release_artifact_downloaded}')
    return release_artifact_downloaded


def get_manifest_yaml(version, manifest_file = 'manifest.yaml'):
    with open(manifest_file, 'r') as f:
        file_content = f.read()

    new_file_content = file_content.replace('${release.version}', version) # change this
    yaml_obj = yaml.safe_load(new_file_content)
    return yaml_obj


def process_manifest_yaml(yaml_data, parent=None):
    '''
    Returns a dict with parent as value, child as key.
    {'pad-ee-9.5.1.0-dist.zip': 'ee/client-tools',
     'pdi-ee-client-9.5.1.0-dist.zip': 'ee/client-tools',
     'pentaho-analysis-ee-9.5.1.0-dist.zip': 'ee/client-tools',
     'pentaho-big-data-ee-package-9.5.1.0-dist.zip': 'ee/client-tools',
     'pme-ee-9.5.1.0-dist.zip': 'ee/client-tools',
     'prd-ee-9.5.1.0-dist.zip': 'ee/client-tools',
     ...}
    
    '''
    result = {}
    for key, value in yaml_data.items():
        current_key = key if parent is None else f"{parent}/{key}"
        if isinstance(value, dict):
            result.update(process_manifest_yaml(value, parent=current_key))
        elif isinstance(value, list):
            for item in value:
                if '$' not in item or '{' not in item:
                    result[item] = current_key
    logging.info(f'Read manifest {result}')
    return result


def get_manifest_buildinfo_intersect(file_folder_dict, builds_output_json):
    d = {}
    manifest_files = set(file_folder_dict.keys()).intersection(set([artifact['path'].split('/')[-1] for artifact in builds_output_json]))
    manifest_files
    for file_to_release in manifest_files:
        d[file_to_release] = file_folder_dict[file_to_release]
        d[file_to_release + '.sum'] =  file_folder_dict[file_to_release]
    return d


def set_box_client(client_id, client_secret, box_subject_id):
    token=generate_access_token(client_id,client_secret,box_subject_id)
    oauth = OAuth2(
        client_id=client_id,
        client_secret=client_secret,
        access_token=token,  
    )

    return Client(oauth)


def upload_one_artifact_to_box(folder_id, file_name, client):

    with open(file_name, 'rb') as file:
        box_file = client.folder(folder_id).upload_stream(file, file_name)
    # Here we have to catch network issue and file not found error etc., right now it does fail the script
    
    logging.info('Uploaded file ID:', box_file.id)


def generate_access_token(client_id, client_secret, box_subject_id):
    url = "https://api.box.com/oauth2/token"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "client_id": client_id,
        "client_secret":client_secret,
        "grant_type": "client_credentials",
        "box_subject_type": "enterprise",
        "box_subject_id": box_subject_id,
    }

    response = requests.post(url, headers=headers, data=data)
    response_data = response.json()
    return response_data['access_token']

def box_create_one_folder(parent_folder_id, folder_name_to_create, client):
    
    try:
        folder = client.folder(parent_folder_id).create_subfolder(folder_name_to_create)
        return folder
    except BoxAPIException as e:
        # if the folder already exists, return the Folder object
        if e.code == 'item_name_in_use': 
            logging.info(f'Folder name {folder_name_to_create} already exist.')
            folder = client.folder(folder_id=e.context_info['conflicts'][0]['id']).get()
            return folder
        return None

def box_create_folder(client, box_folder_parent_id=None):
    d = {}
    
    # ee stuff
    d['ee'] = box_create_one_folder(box_folder_parent_id, 'ee', client)
    d['ee/client-tools'] = box_create_one_folder(d['ee'].id, 'client-tools', client)
    d['ee/installers'] = box_create_one_folder(d['ee'].id, 'installers', client)
    d['ee/other'] = box_create_one_folder(d['ee'].id, 'other', client)
    d['ee/patches'] = box_create_one_folder(d['ee'].id, 'patches', client)
    d['ee/plugins'] = box_create_one_folder(d['ee'].id, 'plugins', client)
    d['ee/server'] = box_create_one_folder(d['ee'].id, 'server', client)
    d['ee/shims'] = box_create_one_folder(d['ee'].id, 'shims', client)
    d['ee/upgrade'] = box_create_one_folder(d['ee'].id, 'upgrade', client)
    
    # ce stuff
    d['ce'] = box_create_one_folder(box_folder_parent_id, 'ce', client)
    d['ce/client-tools'] = box_create_one_folder(d['ce'].id, 'client-tools', client)
    d['ce/plugins'] = box_create_one_folder(d['ce'].id, 'plugins', client)
    d['ce/server'] = box_create_one_folder(d['ce'].id, 'server', client)
    d['ce/other'] = box_create_one_folder(d['ce'].id, 'other', client)
    
    return d

def upload_to_box(client, artifacts_to_release, artifact_to_box_path):
    for artifact, target_box_path in tqdm(artifacts_to_release.items()):
        print(f'Uploading {artifact} up to {artifact_to_box_path[target_box_path]}')
        upload_one_artifact_to_box(artifact_to_box_path[target_box_path].id, artifact, client)
        

if __name__ == '__main__':

    parser = argparse.ArgumentParser()

    parser.add_argument("--client_id", action="store")
    parser.add_argument("--client_secret", action="store", help="box client secret")
    parser.add_argument("--box_subject_id", action="store", help="box box subject id")
    parser.add_argument("--build_name", action="store", help="build name")
    parser.add_argument("--build_number", action="store", help="box client secret")
    parser.add_argument("--rt_auth_username", action="store", help="box client secret")
    parser.add_argument("--rt_auth_password", action="store", help="box client secret")
    parser.add_argument("--box_root_folder_name", action="store", help="box client secret")
    parser.add_argument("--manifest_file_path", action="store", help="box client secret")
    parser.add_argument("--rt_base_url", action="store", help="box client secret")

    args = parser.parse_args()

    client_id = args.client_id
    client_secret = args.client_secret
    box_subject_id = args.box_subject_id
    build_name = args.build_name  # for rt buildinfo query
    build_number = args.build_number  # for rt buildinfo query
    rt_auth = ( args.rt_auth_username, args.rt_auth_password)
    box_root_folder_name = args.box_root_folder_name
    manifest_file_path = args.manifest_file_path
    rt_base_url = args.rt_base_url


    # set up box client
    box_client = set_box_client(client_id, client_secret, box_subject_id)

    # create root folder
    root_folder = box_create_one_folder('261814384', box_root_folder_name, box_client)

    # downloads artifacts
    builds_output_json, artifacts_in_build_info = get_artifact_info_json(build_name, build_number, rt_auth=rt_auth)
    file_folder_dict = process_manifest_yaml(get_manifest_yaml(build_number, manifest_file = manifest_file_path))
    artifacts_to_release = get_manifest_buildinfo_intersect(file_folder_dict, builds_output_json)
    downloaded_artifacts = download_artifacts_v3(artifacts_to_release, builds_output_json, auth=rt_auth, rt_base_url = rt_base_url)

    # uploading to box
    artifact_to_box_path = box_create_folder(box_client, box_folder_parent_id=root_folder.id)
    upload_to_box(box_client, artifacts_to_release, artifact_to_box_path)



