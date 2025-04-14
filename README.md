# GCP Cloud Audit Automation

This repository contains a Python-based automation script designed to audit Google Cloud Platform (GCP) resources for cost optimization. The script identifies unused or underutilized resources, calculates potential cost savings, and generates a detailed report that is pushed to a Confluence page.


---

## Features

- **Audit GCP Resources**:
  - Terminated Virtual Machines (VMs)
  - Unused Disks
  - Unused Static IPs
  - Unused Storage Buckets
  - Unused Backend Services
- **Cost Estimation**:
  - Calculates potential monthly cost savings for unused resources.
- **Confluence Integration**:
  - Generates a detailed HTML table report and pushes it to a specified Confluence page.
- **Firebase Integration**:
  - Stores findings and cost savings data in Firebase Firestore for further analysis.
- **Logging**:
  - Provides detailed logs for debugging and monitoring.

---

## Prerequisites

1. **Google Cloud Platform**:
   - A GCP service account with the necessary permissions to access and audit resources.
   - A JSON key for the service account stored as a GitHub secret (`GCP_SERVICE_ACCOUNT_KEY`).

2. **Firebase**:
   - A Firebase project with Firestore enabled.
   - A Firebase Admin SDK JSON key stored as a GitHub secret (`FIREBASE_CREDENTIALS_JSON`).

3. **Confluence**:
   - A Confluence account with API access.
   - Confluence username and API token stored as environment variables (`CONFLUENCE_USERNAME` and `CONFLUENCE_API_TOKEN`).

4. **Python**:
   - Python 3.9 or higher installed locally or in the CI environment.

---

## Sample Output


| Category                | Status/Details                                                                 | Estimated Monthly Cost |
|-------------------------|-------------------------------------------------------------------------------|-------------------------|
| Terminated VMs          | Name: `vm-1`<br>Zone: `us-central1-a`<br>Status: `TERMINATED`<br>Terminated Time: `2023-04-01 12:00:00`<br>URL: [View Instance](https://console.cloud.google.com/compute/instancesDetail/zones/us-central1-a/instances/vm-1?project=project-id) | $0.00                  |
| Unused Disks            | Name: `disk-1`<br>Zone: `us-central1-a`<br>Size: `50 GB`<br>URL: [View Disk](https://console.cloud.google.com/compute/disksDetail/zones/us-central1-a/disks/disk-1?project=project-id) | $10.00                 |
| Unused Static IPs       | Name: `ip-1`<br>Region: `us-central1`<br>URL: [View Address](https://console.cloud.google.com/networking/addresses/list?project=project-id&region=us-central1) | $7.20                  |
| Unused Storage Buckets  | Name: `bucket-1`<br>Size: `100 GB`<br>Last Modified: `2023-03-01 12:00:00`<br>URL: [View Bucket](https://console.cloud.google.com/storage/browser/bucket-1?project=project-id) | $2.53                  |





   
