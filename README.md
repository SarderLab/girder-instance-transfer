# Girder Instance Transfer

A reusable Python utility for transferring selected folders, items, files, annotations, metadata, and descriptions between Girder instances.

The tool currently supports transfers such as:

* Athena → Parashurama
* Parashurama → Athena
* Any Girder instance → Another Girder instance

The transfer is restart-safe and can reuse existing destination folders and items while skipping files that have already been copied.

---

## Features

* Transfers one selected Girder folder
* Recursively transfers all child folders
* Transfers all items inside each folder
* Transfers all files inside each item
* Preserves folder metadata
* Preserves item metadata
* Preserves folder and item descriptions
* Reuses existing destination folders
* Reuses existing destination items
* Skips files when the filename and file size already match
* Supports explicit pagination for large folders
* Retries failed downloads and uploads
* Displays transfer progress in the terminal
* Can safely continue after interruption by rerunning the command
* Supports API-key authentication
* Supports username and password authentication
* Supports destination parent types:

  * folder
  * collection
  * user

---

## Repository Files

```text
girder-instance-transfer/
├── girder_transfer.py
├── README.md
├── requirements.txt
├── .gitignore
├── athena_to_parashurama_command.txt
└── parashurama_to_athena_command.txt
```

### `girder_transfer.py`

Main Python script used to transfer folders, items, files, metadata, and descriptions between Girder instances.

### `requirements.txt`

Contains the Python package dependencies required to run the script.

### `athena_to_parashurama_command.txt`

Example command for transferring data from Athena to Parashurama.

### `parashurama_to_athena_command.txt`

Example command for transferring data from Parashurama to Athena.

### `.gitignore`

Prevents API keys, logs, temporary files, whole-slide images, and Python cache files from being committed.

---

## How the Transfer Works

The data flow is:

```text
Source Girder
     ↓
Machine running girder_transfer.py
     ↓
Destination Girder
```

Each file is:

1. Downloaded from the source Girder instance.
2. Stored temporarily on the machine running the script.
3. Uploaded to the destination Girder instance.
4. Removed from temporary storage after the upload completes.

The script processes files one at a time.

This is mainly a network and storage I/O workload. A GPU does not improve transfer speed.

---

## Requirements

* Python 3.10 or newer
* Access to the source Girder instance
* Access to the destination Girder instance
* API keys or username/password credentials for both instances
* Sufficient temporary disk space for the largest individual file
* Network access to both Girder servers

---

## Installation

Clone the repository:

```bash
git clone https://github.com/SarderLab/girder-instance-transfer.git
cd girder-instance-transfer
```

Install the required Python package:

```bash
python -m pip install -r requirements.txt
```

Verify the installation:

```bash
python -c "import girder_client; print('Girder client ready')"
```

Expected output:

```text
Girder client ready
```

---

## API Keys

Generate API keys from both Girder instances.

Do not place real API keys directly inside:

* `girder_transfer.py`
* `README.md`
* committed shell scripts
* command example files
* GitHub issues
* Git commit messages

Store API keys in environment variables.

Example:

```bash
export SOURCE_GIRDER_API_KEY="YOUR_SOURCE_API_KEY"
export DESTINATION_GIRDER_API_KEY="YOUR_DESTINATION_API_KEY"
```

Confirm that the variables are set:

```bash
echo ${SOURCE_GIRDER_API_KEY:+SOURCE_KEY_SET}
echo ${DESTINATION_GIRDER_API_KEY:+DESTINATION_KEY_SET}
```

Expected output:

```text
SOURCE_KEY_SET
DESTINATION_KEY_SET
```

---

## Basic Usage

```bash
python -u girder_transfer.py \
  --source-api "SOURCE_GIRDER_API_URL" \
  --destination-api "DESTINATION_GIRDER_API_URL" \
  --source-api-key "$SOURCE_GIRDER_API_KEY" \
  --destination-api-key "$DESTINATION_GIRDER_API_KEY" \
  --source-folder-id "SOURCE_FOLDER_ID" \
  --destination-parent-id "DESTINATION_PARENT_ID" \
  --destination-parent-type folder
```

### Arguments

| Argument                    | Description                                                |
| --------------------------- | ---------------------------------------------------------- |
| `--source-api`              | Source Girder API URL                                      |
| `--destination-api`         | Destination Girder API URL                                 |
| `--source-api-key`          | API key for the source Girder instance                     |
| `--destination-api-key`     | API key for the destination Girder instance                |
| `--source-folder-id`        | ID of the folder to transfer                               |
| `--destination-parent-id`   | ID of the destination folder, collection, or user          |
| `--destination-parent-type` | Destination parent type: `folder`, `collection`, or `user` |

Girder API URLs normally end with:

```text
/api/v1
```

---

## Athena to Parashurama

Set the API keys:

```bash
export ATHENA_API_KEY="YOUR_ATHENA_API_KEY"
export PARASHURAMA_API_KEY="YOUR_PARASHURAMA_API_KEY"
```

Run:

```bash
python -u girder_transfer.py \
  --source-api "https://athena.rc.ufl.edu/api/v1" \
  --destination-api "https://parashurama.rc.ufl.edu/api/v1" \
  --source-api-key "$ATHENA_API_KEY" \
  --destination-api-key "$PARASHURAMA_API_KEY" \
  --source-folder-id "ATHENA_SOURCE_FOLDER_ID" \
  --destination-parent-id "PARASHURAMA_DESTINATION_PARENT_ID" \
  --destination-parent-type folder
```

An example command is also available in:

```text
athena_to_parashurama_command.txt
```

---

## Parashurama to Athena

Set the API keys:

```bash
export PARASHURAMA_API_KEY="YOUR_PARASHURAMA_API_KEY"
export ATHENA_API_KEY="YOUR_ATHENA_API_KEY"
```

Run:

```bash
python -u girder_transfer.py \
  --source-api "https://parashurama.rc.ufl.edu/api/v1" \
  --destination-api "https://athena.rc.ufl.edu/api/v1" \
  --source-api-key "$PARASHURAMA_API_KEY" \
  --destination-api-key "$ATHENA_API_KEY" \
  --source-folder-id "PARASHURAMA_SOURCE_FOLDER_ID" \
  --destination-parent-id "ATHENA_DESTINATION_PARENT_ID" \
  --destination-parent-type folder
```

An example command is also available in:

```text
parashurama_to_athena_command.txt
```

---

## Finding Girder IDs

The script requires Girder resource IDs, not complete browser URLs.

For example, a browser URL may contain a folder ID such as:

```text
6a21a054b16a6bbe95f43ba7
```

Use only the ID value as:

```bash
--source-folder-id "6a21a054b16a6bbe95f43ba7"
```

The destination parent ID must refer to the folder, collection, or user under which the transferred folder should be created.

---

## Running in the Background

For transfers that must survive an SSH disconnection, use `nohup`.

Run the command as one line:

```bash
nohup python -u girder_transfer.py --source-api "SOURCE_API" --destination-api "DESTINATION_API" --source-api-key "$SOURCE_GIRDER_API_KEY" --destination-api-key "$DESTINATION_GIRDER_API_KEY" --source-folder-id "SOURCE_FOLDER_ID" --destination-parent-id "DESTINATION_PARENT_ID" --destination-parent-type folder > transfer.log 2>&1 &
```

Check whether the process is running:

```bash
ps -ef | grep "[g]irder_transfer.py"
```

Watch the log:

```bash
tail -f transfer.log
```

Press `Ctrl+C` to stop watching the log. This does not stop the transfer.

View the most recent log entries:

```bash
tail -n 50 transfer.log
```

---

## Running on HiPerGator

Long transfers should not run directly on a login node.

Use a Slurm compute job when transferring large datasets.

Example Slurm script:

```bash
#!/bin/bash
#SBATCH --job-name=girder-transfer
#SBATCH --output=girder-transfer-%j.log
#SBATCH --error=girder-transfer-%j.err
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G

module load python

cd /path/to/girder-instance-transfer

python -u girder_transfer.py \
  --source-api "$SOURCE_GIRDER_API" \
  --destination-api "$DESTINATION_GIRDER_API" \
  --source-api-key "$SOURCE_GIRDER_API_KEY" \
  --destination-api-key "$DESTINATION_GIRDER_API_KEY" \
  --source-folder-id "$SOURCE_FOLDER_ID" \
  --destination-parent-id "$DESTINATION_PARENT_ID" \
  --destination-parent-type folder
```

Submit the job:

```bash
sbatch girder_transfer.sbatch
```

Check status:

```bash
squeue -u "$USER"
```

Watch the job output:

```bash
tail -f girder-transfer-JOB_ID.log
```

---

## Restarting an Interrupted Transfer

The script is designed to be rerun safely.

When restarted, it:

* Reuses an existing destination folder with the same name
* Reuses an existing destination item with the same name
* Checks files already present in the destination item
* Skips files when both the filename and size match
* Continues with files that have not yet been transferred

Example output:

```text
Destination folder already exists
Destination item already exists
Skipping existing file
Transferring file
```

A partially uploaded individual file cannot currently resume from the middle. That file will be downloaded and uploaded again.

---

## Transfer Progress

Typical output:

```text
Folder: AI_Ready_QC
Searching destination for folder 'AI_Ready_QC'...
Existing folder found
Listing source items...
Found 337 source item(s)

Item: example.svs
Destination item already exists
Listing destination files
Listing source files
Transferring file
Downloading to temporary path
Uploading to destination
Completed file
```

Check the temporary file while a download is in progress:

```bash
ls -lh /tmp/girder_transfer_* 2>/dev/null
```

Watch it continuously:

```bash
watch -n 2 'ls -lh /tmp/girder_transfer_* 2>/dev/null'
```

---

## Duplicate Handling

The script compares destination files using:

* filename
* file size

If both match, the file is skipped.

Example:

```text
Skipping existing file: example.svs
```

If the filename exists but the size is different, the script attempts to upload the source file again.

The script does not currently compare checksums.

---

## Supported Resources

The current version transfers:

* Folders
* Child folders
* Items
* Files
* Folder descriptions
* Item descriptions
* Folder metadata
* Item metadata

---

## Current Limitations

The current version does not transfer:

* Digital Slide Archive annotations
* HistomicsUI annotation documents
* Folder permissions
* Item permissions
* Access-control lists
* Users
* Groups
* Girder jobs
* Processing history
* Partially uploaded file state
* File checksums
* Deleted-resource synchronization
* True bidirectional synchronization

It is a transfer and restart utility, not a full synchronization system.

---

## Security

Never commit real API keys.

Before committing changes, search the repository for possible secrets:

```bash
grep -RniE "api[_-]?key|password|token|secret" .
```

Review Git status:

```bash
git status
```

Review staged changes:

```bash
git diff --cached
```

If an API key is accidentally exposed:

1. Revoke it immediately.
2. Generate a new key.
3. Remove the old key from files.
4. Remove it from Git history if it was committed.
5. Do not continue using the exposed key.

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'girder_client'`

Install the dependency:

```bash
python -m pip install -r requirements.txt
```

### `HTTP error 400`

Confirm:

* The source folder ID is correct
* The destination parent ID is correct
* The destination parent type is correct
* The account has permission to access the resource
* The API endpoint ends with `/api/v1`

### `HTTP error 401` or `HTTP error 403`

The API key may be invalid, expired, revoked, or missing permissions.

Generate a new API key and retry.

### Transfer stops after SSH disconnect

Run the script with `nohup`, `tmux`, `screen`, or a Slurm job.

### Destination folder exists but contains no files

Check the transfer log for:

* item creation errors
* file-listing errors
* upload errors
* interrupted downloads
* authentication failures

### No temporary file appears

The script may still be listing folders or items and may not have started downloading files yet.

---

## Recommended Future Improvements

Possible future additions include:

* Digital Slide Archive annotation transfer
* Permission and access-control transfer
* Checksum verification
* Parallel file transfers
* Dry-run mode
* Transfer summary reports
* Failed-item reports
* Automatic Slurm job templates
* Config-file support
* Progress bars
* Structured logging
* Unit tests
* Continuous integration

---

## Contributing

1. Create a new branch.
2. Make the required changes.
3. Test the transfer using a small folder.
4. Confirm that no credentials are included.
5. Submit a pull request.

Example:

```bash
git checkout -b feature/your-feature-name
git add .
git commit -m "Describe the change"
git push origin feature/your-feature-name
```

---

