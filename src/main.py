import google.auth
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import sys
from datetime import datetime, timedelta, timezone
import logging
import requests
from requests.auth import HTTPBasicAuth
import re
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
import json
from google.oauth2 import service_account
import os
 


service_account_key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
credentials = service_account.Credentials.from_service_account_info(json.loads(service_account_key))


# Load Firebase credentials from an environment variable
firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
if not firebase_credentials_json:
    raise ValueError("FIREBASE_CREDENTIALS_JSON environment variable is not set or empty")

try:
    # Parse the JSON string into a dictionary
    firebase_credentials = json.loads(firebase_credentials_json)
except json.JSONDecodeError as e:
    raise ValueError("FIREBASE_CREDENTIALS_JSON is not a valid JSON string") from e

# Initialize Firebase Admin SDK
cred = credentials.Certificate(firebase_credentials)
initialize_app(cred)
db = firestore.client()

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Confluence configuration
CONFLUENCE_BASE_URL = 'https://example.atlassian.net/wiki'
CONFLUENCE_USERNAME = ''
CONFLUENCE_API_TOKEN = ''

# Estimated costs (these are example values, you should replace them with actual costs)
COST_PER_TERMINATED_VM = 0              # Example cost per terminated VM per month
COST_PER_UNUSED_DISK_GB = 0.2           # Example cost per GB of unused disk per month
COST_PER_UNUSED_STATIC_IP = 7.2         # Example cost per unused static IP per month
COST_PER_UNUSED_STORAGE_GB = 0.0253     # Example cost per GB of unused storage per month

def is_compute_api_enabled(project_id):
    logging.debug(f"Checking if Compute API is enabled for project {project_id}")
    try:
        credentials, _ = google.auth.default()
        service = build('serviceusage', 'v1', credentials=credentials, cache_discovery=False)
        request = service.services().get(name=f'projects/{project_id}/services/compute.googleapis.com')
        response = request.execute()
        
        enabled = response['state'] == 'ENABLED'
        logging.debug(f"Compute API enabled for project {project_id}: {enabled}")
        return enabled
    except Exception as e:
        logging.error(f"Error checking Compute API status for project {project_id}: {e}")
        return False

def list_terminated_vms(project_id):
    logging.debug(f"Listing terminated VMs for project {project_id}")
    output = []
    # Format for category column with colored status label showing project ID
    def formatted_category(name):
        return f"{name} <ac:structured-macro ac:name='status'><ac:parameter ac:name='title'>{project_id}</ac:parameter><ac:parameter ac:name='color'>Red</ac:parameter></ac:structured-macro>"

    if project_id.startswith("sys"):
        output.append([formatted_category("Terminated VMs"), "Skipping checks for system project", "N/A"])
        logging.debug(f"Skipping terminated VM checks for system project {project_id}")
        return output

    if not is_compute_api_enabled(project_id):
        output.append([formatted_category("Terminated VMs"), "Compute API is disabled for project", "N/A"])
        logging.debug(f"Compute API is disabled for project {project_id}")
        return output
    
    try:
        credentials, _ = google.auth.default()
        service = build('compute', 'v1', credentials=credentials, cache_discovery=False)
        request = service.instances().aggregatedList(project=project_id)
        while request is not None:
            response = request.execute()
            if 'items' not in response:
                break
            for zone, instances in response['items'].items():
                if 'instances' in instances:
                    for instance in instances['instances']:
                        if instance['status'] == 'TERMINATED':
                            terminated_time = datetime.fromisoformat(
                                instance['lastStartTimestamp'].replace('Z', '+00:00')
                            ).strftime('%Y-%m-%d %H:%M:%S')
                            instance_url = (
                                f"https://console.cloud.google.com/compute/instancesDetail/zones/"
                                f"{zone.split('/')[-1]}/instances/{instance['name']}?project={project_id}"
                            )
                            cost = COST_PER_TERMINATED_VM
                            output.append([
                                formatted_category("Terminated VMs"),
                                f"Name: <code>{instance['name']}</code>"
                                f"<br>Zone: {zone}"
                                f"<br>Status: {instance['status']}"
                                f"<br>Terminated Time: {terminated_time}"
                                f"<br>URL: <a href='{instance_url}'>View Instance</a>",
                                f"${cost:.2f}"
                            ])
                            logging.debug(f"Found terminated VM: {instance['name']} in project {project_id}")
            request = service.instances().aggregatedList_next(previous_request=request, previous_response=response)
        if not output:
            output.append([formatted_category("Terminated VMs"), "No terminated VMs found in the project", "N/A"])
            logging.debug(f"No terminated VMs found in project {project_id}")
    except Exception as e:
        logging.error(f"Error fetching VM instances for project {project_id}: {e}")
        output.append([formatted_category("Terminated VMs"), f"Error fetching VM instances: {str(e)}", "N/A"])
    return output

def list_unused_disks(project_id):
    logging.debug(f"Listing unused disks for project {project_id}")
    output = []
    def formatted_category(name):
        return f"{name} <ac:structured-macro ac:name='status'><ac:parameter ac:name='title'>{project_id}</ac:parameter><ac:parameter ac:name='color'>Red</ac:parameter></ac:structured-macro>"

    if project_id.startswith("sys"):
        output.append([formatted_category("Unused Disks"), "Skipping checks for system project", "N/A"])
        logging.debug(f"Skipping unused disk checks for system project {project_id}")
        return output

    if not is_compute_api_enabled(project_id):
        output.append([formatted_category("Unused Disks"), "Compute API is disabled for project", "N/A"])
        logging.debug(f"Compute API is disabled for project {project_id}")
        return output
    
    try:
        credentials, _ = google.auth.default()
        service = build('compute', 'v1', credentials=credentials, cache_discovery=False)
        request = service.disks().aggregatedList(project=project_id)
        while request is not None:
            response = request.execute()
            if 'items' not in response:
                break
            for zone, disks in response['items'].items():
                if 'disks' in disks:
                    for disk in disks['disks']:
                        if not disk.get('users', []):
                            size_gb = float(disk['sizeGb'])
                            disk_url = (
                                f"https://console.cloud.google.com/compute/disksDetail/zones/"
                                f"{zone.split('/')[-1]}/disks/{disk['name']}?project={project_id}"
                            )
                            cost = size_gb * COST_PER_UNUSED_DISK_GB
                            output.append([
                                formatted_category("Unused Disks"),
                                f"Name: <code>{disk['name']}</code>"
                                f"<br>Zone: {zone}"
                                f"<br>Size: {size_gb} GB"
                                f"<br>URL: <a href='{disk_url}'>View Disk</a>",
                                f"${cost:.2f}"
                            ])
                            logging.debug(f"Found unused disk: {disk['name']} in project {project_id}")
            request = service.disks().aggregatedList_next(previous_request=request, previous_response=response)
        if not output:
            output.append([formatted_category("Unused Disks"), "No unused disks found in the project", "N/A"])
            logging.debug(f"No unused disks found in project {project_id}")
    except Exception as e:
        logging.error(f"Error fetching disks for project {project_id}: {e}")
        output.append([formatted_category("Unused Disks"), f"Error fetching disks: {str(e)}", "N/A"])
    return output

def list_unused_static_ips(project_id):
    logging.debug(f"Listing unused static IPs for project {project_id}")
    output = []
    def formatted_category(name):
        return f"{name} <ac:structured-macro ac:name='status'><ac:parameter ac:name='title'>{project_id}</ac:parameter><ac:parameter ac:name='color'>Red</ac:structured-macro>"

    if project_id.startswith("sys"):
        output.append([formatted_category("Unused Static IPs"), "Skipping checks for system project", "N/A"])
        logging.debug(f"Skipping unused static IP checks for system project {project_id}")
        return output

    if not is_compute_api_enabled(project_id):
        output.append([formatted_category("Unused Static IPs"), "Compute API is disabled for project", "N/A"])
        logging.debug(f"Compute API is disabled for project {project_id}")
        return output
    
    try:
        credentials, _ = google.auth.default()
        service = build('compute', 'v1', credentials=credentials, cache_discovery=False)
        request = service.addresses().aggregatedList(project=project_id)
        while request is not None:
            response = request.execute()
            if 'items' not in response:
                break
            for region, addresses in response['items'].items():
                if 'addresses' in addresses:
                    for address in addresses['addresses']:
                        if address['status'] == 'RESERVED' and not address.get('users', []):
                            address_url = (
                                f"https://console.cloud.google.com/networking/addresses/list?project={project_id}"
                                f"&region={region.split('/')[-1]}"
                            )
                            cost = COST_PER_UNUSED_STATIC_IP
                            output.append([
                                formatted_category("Unused Static IPs"),
                                f"Name: <code>{address['name']}</code>"
                                f"<br>Region: {region}"
                                f"<br>URL: <a href='{address_url}'>View Address</a>",
                                f"${cost:.2f}"
                            ])
                            logging.debug(f"Found unused static IP: {address['name']} in project {project_id}")
            request = service.addresses().aggregatedList_next(previous_request=request, previous_response=response)
        if not output:
            output.append([formatted_category("Unused Static IPs"), "No unused static IP addresses found in the project", "N/A"])
            logging.debug(f"No unused static IP addresses found in project {project_id}")
    except Exception as e:
        logging.error(f"Error fetching static IP addresses for project {project_id}: {e}")
        output.append([formatted_category("Unused Static IPs"), f"Error fetching static IP addresses: {str(e)}", "N/A"])
    return output

def check_bucket(bucket, thirty_days_ago, storage_service, project_id):
    logging.debug(f"Checking bucket {bucket['name']} for project {project_id}")
    output = []
    bucket_name = bucket['name']
    def formatted_category(name):
        return f"{name} <ac:structured-macro ac:name='status'><ac:parameter ac:name='title'>{project_id}</ac:parameter><ac:parameter ac:name='color'>Red</ac:parameter></ac:structured-macro>"

    try:
        request = storage_service.objects().list(bucket=bucket_name)
        response = request.execute()
        if 'items' in response:
            latest_object = response['items'][0]
            last_modified = datetime.fromisoformat(latest_object['updated'].replace('Z', '+00:00'))
            if last_modified <= thirty_days_ago:
                bucket_size = sum(int(obj['size']) for obj in response['items'])
                bucket_size_gb = bucket_size / (1024 ** 3)  # Convert size to GB
                cost = bucket_size_gb * COST_PER_UNUSED_STORAGE_GB
                bucket_url = f"https://console.cloud.google.com/storage/browser/{bucket_name}?project={project_id}"
                output.append([
                    formatted_category("Unused Storage Buckets"),
                    f"Name: <code>{bucket_name}</code>"
                    f"<br>Size: {bucket_size_gb:.2f} GB"
                    f"<br>Last Modified: {last_modified.strftime('%Y-%m-%d %H:%M:%S')}"
                    f"<br>URL: <a href='{bucket_url}'>View Bucket</a>",
                    f"${cost:.2f}"
                ])
                logging.debug(f"Found unused storage bucket: {bucket_name} in project {project_id}")
        else:
            logging.debug(f"No objects found in bucket {bucket_name} for project {project_id}")
    except HttpError as e:
        if e.resp.status == 403:
            output.append([
                formatted_category("Unused Storage Buckets"),
                f"Access denied for bucket <code>{bucket_name}</code>",
                "N/A"
            ])
            logging.debug(f"Access denied for bucket {bucket_name} in project {project_id}")
        else:
            logging.error(f"Error fetching objects for bucket {bucket_name}: {e}")
            output.append([
                formatted_category("Unused Storage Buckets"),
                f"Error fetching objects for bucket <code>{bucket_name}</code>: {str(e)}",
                "N/A"
            ])
    return output

def list_unused_storage_buckets(project_id):
    logging.debug(f"Listing unused storage buckets for project {project_id}")
    output = []
    def formatted_category(name):
        return f"{name} <ac:structured-macro ac:name='status'><ac:parameter ac:name='title'>{project_id}</ac:parameter><ac:parameter ac:name='color'>Red</ac:parameter></ac:structured-macro>"

    if project_id.startswith("sys"):
        output.append([formatted_category("Unused Storage Buckets"), "Skipping checks for system project", "N/A"])
        logging.debug(f"Skipping unused storage bucket checks for system project {project_id}")
        return output

    try:
        credentials, _ = google.auth.default()
        storage_service = build('storage', 'v1', credentials=credentials, cache_discovery=False)
        request = storage_service.buckets().list(project=project_id)
        buckets = []
        while request is not None:
            response = request.execute()
            buckets.extend(response.get('items', []))
            request = storage_service.buckets().list_next(previous_request=request, previous_response=response)
        
        if not buckets:
            output.append([formatted_category("Unused Storage Buckets"), "No storage buckets found in the project", "N/A"])
            logging.debug(f"No storage buckets found in project {project_id}")
            return output
        
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        
        valid_buckets_found = False
        for bucket in buckets:
            bucket_output = check_bucket(bucket, thirty_days_ago, storage_service, project_id)
            if bucket_output:
                valid_buckets_found = True
                output.extend(bucket_output)
        
        if not valid_buckets_found:
            output.append([formatted_category("Unused Storage Buckets"), "No unused storage buckets found in the project", "N/A"])
            logging.debug(f"No unused storage buckets found in project {project_id}")
    except Exception as e:
        logging.error(f"Error fetching storage bucket data for project {project_id}: {e}")
        output.append([
            formatted_category("Unused Storage Buckets"),
            f"Error fetching storage bucket data: {str(e)}",
            "N/A"
        ])
    return output

def push_to_confluence(page_url, content):
    logging.debug(f"Pushing content to Confluence page {page_url}")
    page_id_match = re.search(r'/pages/viewpage.action\?pageId=(\d+)', page_url)
    if not page_id_match:
        page_id_match = re.search(r'/spaces/.+/pages/(\d+)', page_url)
        if not page_id_match:
            logging.error("Invalid Confluence page URL. Expected format: https://<your-confluence-instance>/wiki/pages/viewpage.action?pageId=<page_id> or https://<your-confluence-instance>/wiki/spaces/<space_key>/pages/<page_id>")
            return
    
    page_id = page_id_match.group(1)
    url = f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}"
    headers = {"Content-Type": "application/json"}
    auth = HTTPBasicAuth(CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN)
    
    response = requests.get(url, headers=headers, auth=auth, verify=False)
    if response.status_code != 200:
        logging.error(f"Failed to get Confluence page: {response.status_code} - {response.text}")
        return
    
    response_data = response.json()
    version = response_data['version']['number'] + 1
    
    data = {
        "id": page_id,
        "type": "page",
        "title": response_data['title'],
        "space": {"key": response_data['space']['key']},
        "version": {"number": version},
        "body": {
            "storage": {
                "value": content,
                "representation": "storage"
            }
        }
    }
    
    response = requests.put(url, headers=headers, auth=auth, json=data, verify=False)
    if response.status_code == 200:
        logging.info(f"Successfully pushed content to Confluence page '{response_data['title']}'")
    else:
        logging.error(f"Failed to push content to Confluence: {response.status_code} - {response.text}")

def generate_confluence_table(headers, rows):
    logging.debug("Generating Confluence table")
    table_header = ''.join([
        f'<th style="padding: 8px; background-color: #f2f2f2;">{header}</th>' 
        for header in headers
    ])
    table_rows = ''.join([
        '<tr>' + ''.join([
            f'<td style="padding: 8px; background-color:{"#ffcccc" if "No" not in cell else "#ccffcc"}">'
            f'{cell}</td>'
            for cell in row
        ]) + '</tr>'
        for row in rows
    ])
    return (
        f'<table style="border-collapse: collapse; width: 100%; border: 1px solid #ddd;">'
        f'<thead><tr>{table_header}</tr></thead>'
        f'<tbody>{table_rows}</tbody></table>'
    )

def list_unused_backend_services(project_id):
    logging.debug(f"Listing unused backend services for project {project_id}")
    output = []
    def formatted_category(name):
        return f"{name} <ac:structured-macro ac:name='status'><ac:parameter ac:name='title'>{project_id}</ac:parameter><ac:parameter ac:name='color'>Red</ac:parameter></ac:structured-macro>"

    if project_id.startswith("sys"):
        output.append([formatted_category("Unused Backend Services"), "Skipping checks for system project", "N/A"])
        logging.debug(f"Skipping unused backend services checks for system project {project_id}")
        return output

    if not is_compute_api_enabled(project_id):
        output.append([formatted_category("Unused Backend Services"), "Compute API is disabled for project", "N/A"])
        logging.debug(f"Compute API is disabled for project {project_id}")
        return output
    
    try:
        credentials, _ = google.auth.default()
        service = build('compute', 'v1', credentials=credentials, cache_discovery=False)
        request = service.backendServices().list(project=project_id)
        while request is not None:
            response = request.execute()
            if 'items' not in response:
                break
            for backend_service in response['items']:
                if not backend_service.get('backends', []):
                    backend_service_url = (
                        f"https://console.cloud.google.com/networking/backendServices/details/{backend_service['name']}?project={project_id}"
                    )
                    cost = 0  # Define the cost for unused backend services if applicable
                    output.append([
                        formatted_category("Unused Backend Services"),
                        f"Name: <code>{backend_service['name']}</code>"
                        f"<br>URL: <a href='{backend_service_url}'>View Backend Service</a>",
                        f"${cost:.2f}"
                    ])
                    logging.debug(f"Found unused backend service: {backend_service['name']} in project {project_id}")
            request = service.backendServices().list_next(previous_request=request, previous_response=response)
        if not output:
            output.append([formatted_category("Unused Backend Services"), "No unused backend services found in the project", "N/A"])
            logging.debug(f"No unused backend services found in project {project_id}")
    except Exception as e:
        logging.error(f"Error fetching backend services for project {project_id}: {e}")
        output.append([formatted_category("Unused Backend Services"), f"Error fetching backend services: {str(e)}", "N/A"])
    return output


# ...existing code...

def process_project(project_id, owner_name):
    logging.debug(f"Processing project {project_id}")
    if project_id.startswith("sys"):
        logging.debug(f"Skipping checks for system project: {project_id}")
        return (
            f"<tr><td><h2>Project: <code>{project_id}</code></h2>"
            "Skipping checks for system project</td></tr>"
        )

    logging.info(f"Processing project: {project_id}")
    output = []
    findings_count = {
        "Terminated VMs": 0,
        "Unused Disks": 0,
        "Unused Static IPs": 0,
        "Unused Storage Buckets": 0,
        "Unused Backend Services": 0
    }

    # Process each category and count findings
    terminated_vms = list_terminated_vms(project_id)
    findings_count["Terminated VMs"] += len([row for row in terminated_vms if row[2] != "N/A"])
    output.extend(terminated_vms)

    unused_disks = list_unused_disks(project_id)
    findings_count["Unused Disks"] += len([row for row in unused_disks if row[2] != "N/A"])
    output.extend(unused_disks)

    unused_static_ips = list_unused_static_ips(project_id)
    findings_count["Unused Static IPs"] += len([row for row in unused_static_ips if row[2] != "N/A"])
    output.extend(unused_static_ips)

    unused_storage_buckets = list_unused_storage_buckets(project_id)
    findings_count["Unused Storage Buckets"] += len([row for row in unused_storage_buckets if row[2] != "N/A"])
    output.extend(unused_storage_buckets)

    unused_backend_services = list_unused_backend_services(project_id)
    findings_count["Unused Backend Services"] += len([row for row in unused_backend_services if row[2] != "N/A"])
    output.extend(unused_backend_services)

    # Calculate total estimated monthly cost
    total_cost = sum(
        float(row[2].replace('$', '')) for row in output if row[2] != "N/A"
    )

    # Add total cost row at the top
    total_cost_row = [
        f"<strong>Total Estimated Monthly Cost Savings</strong>",
        "",
        f"<strong>${total_cost:.2f}</strong>"
    ]
    output.insert(0, total_cost_row)

    # Organize the output in a tabular format
    headers = ["Category", "Status/Details", "Estimated Monthly Cost"]
    project_table = generate_confluence_table(headers, output)

    # Push findings count and total cost to Firebase under the owner name
   # try:
   #     #db.collection('test-resources-review').document(owner_name).set({
   #         project_id: {
   ##             "findings_count": findings_count,
   #             "total_cost_savings": total_cost
   #         }
   #     }, merge=True)  # Use merge=True to avoid overwriting existing data
   #     logging.info(f"Successfully pushed findings for project {project_id} under owner {owner_name} to Firebase")
   # except Exception as e:
   #     logging.error(f"Error pushing findings to Firebase for project {project_id} under owner {owner_name}: {e}")

    return f"<tr><td><h2>Project: <code>{project_id}</code></h2>{project_table}</td></tr>"
# ...existing code...

def generate_summary_table(owner, team, current_date, total_savings):
    logging.debug("Generating summary table")
    summary_table = (
        f'<table style="border-collapse: collapse; width: 100%; border: 1px solid #ddd;">'
        f'<thead><tr>'
        f'<th style="padding: 8px; background-color: #f2f2f2;">Owner</th>'
        f'<th style="padding: 8px; background-color: #f2f2f2;">Team</th>'
        f'<th style="padding: 8px; background-color: #f2f2f2;">Date</th>'
        f'<th style="padding: 8px; background-color: #f2f2f2;">Total Estimated Monthly Cost Savings</th>'
        f'</tr></thead>'
        f'<tbody><tr>'
        f'<td style="padding: 8px;">{owner}</td>'
        f'<td style="padding: 8px;">{team}</td>'
        f'<td style="padding: 8px;">{current_date}</td>'
        f'<td style="padding: 8px;"><strong>${total_savings:.2f}</strong></td>'
        f'</tr></tbody></table>'
    )
    return summary_table

# ...existing code...

if __name__ == "__main__":
    logging.debug("Starting script")
    if len(sys.argv) < 6:
        print("Usage: python script-all.py <confluence_page_url> <owner> <team> <current_date> <project_id1> <project_id2> ...")
        sys.exit(1)
    
    confluence_page_url = sys.argv[1]
    owner = sys.argv[2]
    team = sys.argv[3]
    current_date = sys.argv[4]
    project_ids = sys.argv[5:]
    
    overall_output = []
    total_savings = 0
    for project_id in project_ids:
        try:
            result = process_project(project_id, owner)
            overall_output.append(result)
            logging.info(f"Successfully processed project {project_id}")
            total_savings += float(re.search(r'<strong>\$(\d+\.\d+)</strong>', result).group(1))
        except Exception as e:
            logging.error(f"Error processing project {project_id}: {e}")
    
    summary_table = generate_summary_table(owner, team, current_date, total_savings)
    
    # Combine all project tables into one content
    confluence_content = (
        summary_table +
        f'<table style="border-collapse: collapse; width: 100%; border: 1px solid #ddd;">'
        f'<tbody>{"".join(overall_output)}</tbody></table>'
    )
    push_to_confluence(confluence_page_url, confluence_content)
    logging.debug("Script finished")
