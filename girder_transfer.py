#!/usr/bin/env python3

import argparse
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import girder_client


def connect(
    api_url: str,
    api_key: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> girder_client.GirderClient:
    """Connect and authenticate to a Girder instance."""
    gc = girder_client.GirderClient(apiUrl=api_url.rstrip("/"))

    if api_key:
        gc.authenticate(apiKey=api_key)
    elif username and password:
        gc.authenticate(username=username, password=password)
    else:
        raise ValueError(
            "Provide either an API key or both username and password."
        )

    return gc


def get_all_resources(
    gc: girder_client.GirderClient,
    path: str,
    parameters: Optional[Dict[str, Any]] = None,
    page_size: int = 100,
    label: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve all Girder resources using explicit bounded pagination.

    This avoids GirderClient list* calls with limit=0, which can repeatedly
    paginate or appear to hang on some Girder installations.
    """
    parameters = dict(parameters or {})
    offset = 0
    results: List[Dict[str, Any]] = []
    display_label = label or path

    while True:
        request_parameters = {
            **parameters,
            "limit": page_size,
            "offset": offset,
        }

        print(
            f"    Listing {display_label}: offset={offset}, limit={page_size}",
            flush=True,
        )

        page = gc.get(path, parameters=request_parameters)

        if not page:
            break

        if not isinstance(page, list):
            raise RuntimeError(
                f"Expected a list from GET {path}, but received "
                f"{type(page).__name__}."
            )

        results.extend(page)

        print(
            f"    Received {len(page)} record(s); total={len(results)}",
            flush=True,
        )

        if len(page) < page_size:
            break

        offset += len(page)

    return results


def find_existing_folder(
    gc: girder_client.GirderClient,
    parent_id: str,
    parent_type: str,
    name: str,
) -> Optional[Dict[str, Any]]:
    """Find an exact-name folder under a specified Girder parent."""
    print(
        f"  Searching destination for folder '{name}'...",
        flush=True,
    )

    folders = gc.get(
        "folder",
        parameters={
            "parentId": parent_id,
            "parentType": parent_type,
            "name": name,
            "limit": 50,
            "offset": 0,
        },
    )

    print(
        f"  Destination returned {len(folders)} folder candidate(s).",
        flush=True,
    )

    for folder in folders:
        if folder.get("name") == name:
            print(
                f"  Existing folder found: {folder['_id']}",
                flush=True,
            )
            return folder

    print("  Existing folder not found.", flush=True)
    return None


def find_existing_item(
    gc: girder_client.GirderClient,
    folder_id: str,
    name: str,
) -> Optional[Dict[str, Any]]:
    """Find an exact-name item in a destination folder."""
    items = gc.get(
        "item",
        parameters={
            "folderId": folder_id,
            "name": name,
            "limit": 50,
            "offset": 0,
        },
    )

    for item in items:
        if item.get("name") == name:
            return item

    return None


def copy_metadata(
    gc_destination: girder_client.GirderClient,
    resource_type: str,
    resource_id: str,
    metadata: Optional[Dict[str, Any]],
) -> None:
    """Copy folder or item metadata."""
    if not metadata:
        return

    try:
        if resource_type == "folder":
            gc_destination.addMetadataToFolder(resource_id, metadata)
        elif resource_type == "item":
            gc_destination.addMetadataToItem(resource_id, metadata)
        else:
            raise ValueError(f"Unsupported metadata resource: {resource_type}")
    except Exception as exc:
        print(
            f"  Warning: could not copy {resource_type} metadata: {exc}",
            flush=True,
        )


def download_file_with_retries(
    gc_source: girder_client.GirderClient,
    source_file_id: str,
    local_path: str,
    filename: str,
    retries: int = 3,
) -> None:
    """Download a Girder file with simple retry handling."""
    for attempt in range(1, retries + 1):
        try:
            gc_source.downloadFile(source_file_id, local_path)
            return
        except Exception as exc:
            if attempt == retries:
                raise

            wait_seconds = attempt * 5
            print(
                f"    Download failed for {filename}: {exc}. "
                f"Retrying in {wait_seconds} seconds...",
                flush=True,
            )
            time.sleep(wait_seconds)


def upload_file_with_retries(
    gc_destination,
    destination_item_id,
    local_path,
    filename,
    mime_type=None,
    retries=3,
):
    """Upload a local file to a Girder item with retries."""

    for attempt in range(1, retries + 1):
        try:
            gc_destination.uploadFileToItem(
                destination_item_id,
                local_path,
                mimeType=mime_type,
                filename=filename,
            )

            return

        except Exception as exc:
            if attempt == retries:
                raise

            wait_seconds = attempt * 5

            print(
                f"    Upload failed for {filename}: {exc}. "
                f"Retrying in {wait_seconds} seconds...",
                flush=True,
            )

            time.sleep(wait_seconds)


def copy_item(
    gc_source: girder_client.GirderClient,
    gc_destination: girder_client.GirderClient,
    source_item: Dict[str, Any],
    destination_folder_id: str,
    skip_existing_files: bool = True,
) -> None:
    """Copy one Girder item and all files belonging to it."""
    item_name = source_item["name"]
    print(f"  Item: {item_name}", flush=True)

    destination_item = find_existing_item(
        gc_destination,
        destination_folder_id,
        item_name,
    )

    if destination_item:
        print(
            f"    Destination item already exists; reusing "
            f"{destination_item['_id']}.",
            flush=True,
        )
    else:
        destination_item = gc_destination.createItem(
        destination_folder_id,
        item_name,
        description=source_item.get("description", ""),
        reuseExisting=True,
        )
        print(
            f"    Created destination item: {destination_item['_id']}",
            flush=True,
        )

    copy_metadata(
        gc_destination,
        "item",
        destination_item["_id"],
        source_item.get("meta", {}),
    )

    destination_files = get_all_resources(
        gc_destination,
        f"item/{destination_item['_id']}/files",
        page_size=100,
        label=f"destination files for '{item_name}'",
    )
    existing_files = {
        file_document["name"]: file_document
        for file_document in destination_files
    }

    source_files = get_all_resources(
        gc_source,
        f"item/{source_item['_id']}/files",
        page_size=100,
        label=f"source files for '{item_name}'",
    )
    if not source_files:
        print("    No files found in this source item.", flush=True)
        return

    for source_file in source_files:
        filename = source_file["name"]
        source_size = source_file.get("size")

        if skip_existing_files and filename in existing_files:
            destination_size = existing_files[filename].get("size")

            if destination_size == source_size:
                print(
                    f"    Skipping existing file: {filename} "
                    f"({source_size} bytes)",
                    flush=True,
                )
                continue

            print(
                f"    File exists but size differs: {filename}. "
                "Uploading a new copy.",
                flush=True,
            )

        print(
            f"    Transferring file: {filename} "
            f"({source_size if source_size is not None else 'unknown'} bytes)",
            flush=True,
        )

        suffix = Path(filename).suffix

        with tempfile.NamedTemporaryFile(
            prefix="girder_transfer_",
            suffix=suffix,
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name

        try:
            print(
                f"    Downloading to temporary path: {temporary_path}",
                flush=True,
            )

            download_file_with_retries(
                gc_source,
                source_file["_id"],
                temporary_path,
                filename,
            )

            downloaded_size = os.path.getsize(temporary_path)

            if source_size is not None and downloaded_size != source_size:
                raise RuntimeError(
                    f"Downloaded size mismatch for {filename}: "
                    f"expected {source_size}, got {downloaded_size}."
                )

            print(
                f"    Uploading {filename} to destination...",
                flush=True,
            )

            upload_file_with_retries(
                gc_destination,
                destination_item["_id"],
                temporary_path,
                filename,
                mime_type=source_file.get("mimeType"),
            )

            print(
                f"    Completed file: {filename}",
                flush=True,
            )

        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)


def copy_folder_recursive(
    gc_source: girder_client.GirderClient,
    gc_destination: girder_client.GirderClient,
    source_folder_id: str,
    destination_parent_id: str,
    destination_parent_type: str = "folder",
    reuse_existing: bool = True,
) -> Dict[str, Any]:
    """Recursively copy one Girder folder hierarchy."""
    source_folder = gc_source.getFolder(source_folder_id)
    folder_name = source_folder["name"]

    print(f"\nFolder: {folder_name}", flush=True)

    destination_folder = None

    if reuse_existing:
        destination_folder = find_existing_folder(
            gc_destination,
            destination_parent_id,
            destination_parent_type,
            folder_name,
        )

    if destination_folder:
        print(
            f"  Destination folder already exists: "
            f"{destination_folder['_id']}",
            flush=True,
        )
    else:
        destination_folder = gc_destination.createFolder(
            parentId=destination_parent_id,
            name=folder_name,
            description=source_folder.get("description", ""),
            parentType=destination_parent_type,
            reuseExisting=reuse_existing,
        )

        print(
            f"  Created destination folder: "
            f"{destination_folder['_id']}",
            flush=True,
        )

    copy_metadata(
        gc_destination,
        "folder",
        destination_folder["_id"],
        source_folder.get("meta", {}),
    )

    print("  Listing source items...", flush=True)

    source_items = get_all_resources(
        gc_source,
        "item",
        parameters={"folderId": source_folder_id},
        page_size=100,
        label=f"items in folder '{folder_name}'",
    )

    print(
        f"  Found {len(source_items)} source item(s).",
        flush=True,
    )

    for source_item in source_items:
        copy_item(
            gc_source,
            gc_destination,
            source_item,
            destination_folder["_id"],
        )

    print("  Listing child folders...", flush=True)

    child_folders = get_all_resources(
        gc_source,
        "folder",
        parameters={
            "parentId": source_folder_id,
            "parentType": "folder",
        },
        page_size=100,
        label=f"child folders of '{folder_name}'",
    )

    print(
        f"  Found {len(child_folders)} child folder(s).",
        flush=True,
    )

    for child_folder in child_folders:
        copy_folder_recursive(
            gc_source,
            gc_destination,
            child_folder["_id"],
            destination_folder["_id"],
            destination_parent_type="folder",
            reuse_existing=reuse_existing,
        )

    return destination_folder


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Recursively transfer one Girder folder between two instances."
        )
    )

    parser.add_argument(
        "--source-api",
        required=True,
        help="Source Girder API URL, e.g. https://source.example/api/v1",
    )
    parser.add_argument(
        "--destination-api",
        required=True,
        help="Destination Girder API URL, e.g. https://dest.example/api/v1",
    )
    parser.add_argument(
        "--source-folder-id",
        required=True,
        help="Girder ID of the source folder to copy",
    )
    parser.add_argument(
        "--destination-parent-id",
        required=True,
        help="Girder ID of the destination parent",
    )
    parser.add_argument(
        "--destination-parent-type",
        choices=["folder", "collection", "user"],
        default="folder",
    )

    parser.add_argument("--source-api-key")
    parser.add_argument("--destination-api-key")

    parser.add_argument("--source-username")
    parser.add_argument("--source-password")
    parser.add_argument("--destination-username")
    parser.add_argument("--destination-password")

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    print("Connecting to source Girder instance...", flush=True)
    gc_source = connect(
        args.source_api,
        api_key=args.source_api_key,
        username=args.source_username,
        password=args.source_password,
    )

    print("Connecting to destination Girder instance...", flush=True)
    gc_destination = connect(
        args.destination_api,
        api_key=args.destination_api_key,
        username=args.destination_username,
        password=args.destination_password,
    )

    source_folder = gc_source.getFolder(args.source_folder_id)

    print("\nTransfer configuration", flush=True)
    print("----------------------", flush=True)
    print(f"Source folder: {source_folder['name']}", flush=True)
    print(f"Source folder ID: {args.source_folder_id}", flush=True)
    print(
        f"Destination parent ID: {args.destination_parent_id}",
        flush=True,
    )
    print(
        f"Destination parent type: {args.destination_parent_type}",
        flush=True,
    )

    result = copy_folder_recursive(
        gc_source,
        gc_destination,
        args.source_folder_id,
        args.destination_parent_id,
        args.destination_parent_type,
    )

    print("\nTransfer completed successfully.", flush=True)
    print(f"Destination folder name: {result['name']}", flush=True)
    print(f"Destination folder ID: {result['_id']}", flush=True)


if __name__ == "__main__":
    main()
