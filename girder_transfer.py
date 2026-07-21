#!/usr/bin/env python3

import argparse
import copy
import json
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
        gc.authenticate(
            username=username,
            password=password,
        )
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
    Retrieve all Girder resources using explicit pagination.

    Explicit bounded pagination avoids limit=0 behavior that can appear
    to hang on some Girder installations.
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
            f"    Listing {display_label}: "
            f"offset={offset}, limit={page_size}",
            flush=True,
        )

        page = gc.get(
            path,
            parameters=request_parameters,
        )

        if not page:
            break

        if not isinstance(page, list):
            raise RuntimeError(
                f"Expected a list from GET {path}, but received "
                f"{type(page).__name__}."
            )

        results.extend(page)

        print(
            f"    Received {len(page)} record(s); "
            f"total={len(results)}",
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
        f"  Destination returned {len(folders)} "
        f"folder candidate(s).",
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
        print(
            f"    No {resource_type} metadata found.",
            flush=True,
        )
        return

    try:
        if resource_type == "folder":
            gc_destination.addMetadataToFolder(
                resource_id,
                metadata,
            )
        elif resource_type == "item":
            gc_destination.addMetadataToItem(
                resource_id,
                metadata,
            )
        else:
            raise ValueError(
                f"Unsupported metadata resource: {resource_type}"
            )

        print(
            f"    Copied {len(metadata)} {resource_type} "
            "metadata field(s).",
            flush=True,
        )

    except Exception as exc:
        print(
            f"    Warning: could not copy "
            f"{resource_type} metadata: {exc}",
            flush=True,
        )


def download_file_with_retries(
    gc_source: girder_client.GirderClient,
    source_file_id: str,
    local_path: str,
    filename: str,
    retries: int = 3,
) -> None:
    """Download one Girder file with retry handling."""

    for attempt in range(1, retries + 1):
        try:
            gc_source.downloadFile(
                source_file_id,
                local_path,
            )
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
    gc_destination: girder_client.GirderClient,
    destination_item_id: str,
    local_path: str,
    filename: str,
    mime_type: Optional[str] = None,
    retries: int = 3,
) -> None:
    """Upload one local file to a Girder item with retries."""

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


def copy_annotations(
    gc_source: girder_client.GirderClient,
    gc_destination: girder_client.GirderClient,
    source_item_id: str,
    destination_item_id: str,
) -> None:
    """
    Copy all annotations from a source item to a destination item.

    Existing destination annotations are compared by normalized name.
    An annotation with the same name is skipped to prevent duplicates.
    """

    source_annotations = get_all_resources(
        gc_source,
        "annotation",
        parameters={
            "itemId": source_item_id,
        },
        page_size=100,
        label=f"source annotations for item {source_item_id}",
    )

    if not source_annotations:
        print(
            "    No annotations found on source item.",
            flush=True,
        )
        return

    destination_annotations = get_all_resources(
        gc_destination,
        "annotation",
        parameters={
            "itemId": destination_item_id,
        },
        page_size=100,
        label=(
            "destination annotations for item "
            f"{destination_item_id}"
        ),
    )

    existing_names = {
        annotation_record
        .get("annotation", {})
        .get("name", "")
        .strip()
        .lower()
        for annotation_record in destination_annotations
    }

    copied = 0
    skipped = 0
    failed = 0

    for source_record in source_annotations:
        annotation_data = copy.deepcopy(
            source_record.get("annotation", {})
        )

        annotation_name = annotation_data.get(
            "name",
            "Unnamed",
        )

        normalized_name = (
            annotation_name
            .strip()
            .lower()
        )

        if not annotation_data:
            print(
                f"    [ANNOTATION EMPTY] {annotation_name}",
                flush=True,
            )
            skipped += 1
            continue

        if normalized_name in existing_names:
            print(
                f"    [ANNOTATION EXISTS] {annotation_name}",
                flush=True,
            )
            skipped += 1
            continue

        try:
            gc_destination.post(
                "annotation",
                parameters={
                    "itemId": destination_item_id,
                },
                data=json.dumps(annotation_data),
                headers={
                    "Content-Type": "application/json",
                },
            )

            existing_names.add(normalized_name)
            copied += 1

            element_count = len(
                annotation_data.get("elements", [])
            )

            print(
                f"    [ANNOTATION COPIED] {annotation_name} "
                f"({element_count} elements)",
                flush=True,
            )

        except Exception as exc:
            failed += 1

            print(
                f"    [ANNOTATION FAILED] "
                f"{annotation_name}: {exc}",
                flush=True,
            )

    print(
        f"    Annotation summary: "
        f"copied={copied}, "
        f"skipped={skipped}, "
        f"failed={failed}, "
        f"source total={len(source_annotations)}",
        flush=True,
    )


def copy_item(
    gc_source: girder_client.GirderClient,
    gc_destination: girder_client.GirderClient,
    source_item: Dict[str, Any],
    destination_folder_id: str,
    skip_existing_files: bool = True,
) -> None:
    """
    Copy one Girder item.

    Includes:
    - item
    - description
    - metadata
    - files
    - annotations
    """

    item_name = source_item["name"]

    print(
        f"\n  Item: {item_name}",
        flush=True,
    )

    destination_item = find_existing_item(
        gc_destination,
        destination_folder_id,
        item_name,
    )

    if destination_item:
        print(
            "    Destination item already exists; "
            f"reusing {destination_item['_id']}.",
            flush=True,
        )

    else:
        destination_item = gc_destination.createItem(
            destination_folder_id,
            item_name,
            description=source_item.get(
                "description",
                "",
            ),
            reuseExisting=True,
        )

        print(
            "    Created destination item: "
            f"{destination_item['_id']}",
            flush=True,
        )

    print(
        "    Copying item metadata...",
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
        print(
            "    No files found in this source item.",
            flush=True,
        )

    copied_files = 0
    skipped_files = 0
    failed_files = 0

    for source_file in source_files:
        filename = source_file["name"]
        source_size = source_file.get("size")

        if skip_existing_files and filename in existing_files:
            destination_size = existing_files[
                filename
            ].get("size")

            if destination_size == source_size:
                print(
                    f"    [FILE EXISTS] {filename} "
                    f"({source_size} bytes)",
                    flush=True,
                )

                skipped_files += 1
                continue

            print(
                f"    File exists but size differs: {filename}. "
                "Uploading another copy.",
                flush=True,
            )

        print(
            f"    [FILE TRANSFER] {filename} "
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
                f"    Downloading to: {temporary_path}",
                flush=True,
            )

            download_file_with_retries(
                gc_source,
                source_file["_id"],
                temporary_path,
                filename,
            )

            downloaded_size = os.path.getsize(
                temporary_path
            )

            if (
                source_size is not None
                and downloaded_size != source_size
            ):
                raise RuntimeError(
                    f"Downloaded size mismatch for {filename}: "
                    f"expected {source_size}, "
                    f"got {downloaded_size}."
                )

            print(
                f"    Uploading: {filename}",
                flush=True,
            )

            upload_file_with_retries(
                gc_destination,
                destination_item["_id"],
                temporary_path,
                filename,
                mime_type=source_file.get("mimeType"),
            )

            copied_files += 1

            print(
                f"    [FILE COPIED] {filename}",
                flush=True,
            )

        except Exception as exc:
            failed_files += 1

            print(
                f"    [FILE FAILED] {filename}: {exc}",
                flush=True,
            )

        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)

    print(
        f"    File summary: copied={copied_files}, "
        f"skipped={skipped_files}, "
        f"failed={failed_files}, "
        f"source total={len(source_files)}",
        flush=True,
    )

    print(
        "    Transferring annotations...",
        flush=True,
    )

    copy_annotations(
        gc_source,
        gc_destination,
        source_item["_id"],
        destination_item["_id"],
    )


def copy_folder_recursive(
    gc_source: girder_client.GirderClient,
    gc_destination: girder_client.GirderClient,
    source_folder_id: str,
    destination_parent_id: str,
    destination_parent_type: str = "folder",
    reuse_existing: bool = True,
) -> Dict[str, Any]:
    """
    Recursively copy a Girder folder hierarchy.

    Includes:
    - source folder
    - folder metadata
    - every item
    - item metadata
    - every item file
    - every item annotation
    - nested child folders
    """

    source_folder = gc_source.getFolder(
        source_folder_id
    )

    folder_name = source_folder["name"]

    print(
        f"\nFolder: {folder_name}",
        flush=True,
    )

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
            "  Destination folder already exists: "
            f"{destination_folder['_id']}",
            flush=True,
        )

    else:
        destination_folder = gc_destination.createFolder(
            parentId=destination_parent_id,
            name=folder_name,
            description=source_folder.get(
                "description",
                "",
            ),
            parentType=destination_parent_type,
            reuseExisting=reuse_existing,
        )

        print(
            "  Created destination folder: "
            f"{destination_folder['_id']}",
            flush=True,
        )

    print(
        "  Copying folder metadata...",
        flush=True,
    )

    copy_metadata(
        gc_destination,
        "folder",
        destination_folder["_id"],
        source_folder.get("meta", {}),
    )

    print(
        "  Listing source items...",
        flush=True,
    )

    source_items = get_all_resources(
        gc_source,
        "item",
        parameters={
            "folderId": source_folder_id,
        },
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

    print(
        "  Listing child folders...",
        flush=True,
    )

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
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Recursively transfer a Girder folder, including "
            "folders, items, metadata, files, and annotations."
        )
    )

    parser.add_argument(
        "--source-api",
        required=True,
        help=(
            "Source Girder API URL, for example "
            "https://athena.rc.ufl.edu/api/v1"
        ),
    )

    parser.add_argument(
        "--destination-api",
        required=True,
        help=(
            "Destination Girder API URL, for example "
            "https://parashurama.rc.ufl.edu/api/v1"
        ),
    )

    parser.add_argument(
        "--source-folder-id",
        required=True,
        help="Girder ID of the source folder to copy",
    )

    parser.add_argument(
        "--destination-parent-id",
        required=True,
        help=(
            "Girder ID of the destination parent under which "
            "the source folder will be created or reused"
        ),
    )

    parser.add_argument(
        "--destination-parent-type",
        choices=[
            "folder",
            "collection",
            "user",
        ],
        default="folder",
    )

    parser.add_argument(
        "--source-api-key",
    )

    parser.add_argument(
        "--destination-api-key",
    )

    parser.add_argument(
        "--source-username",
    )

    parser.add_argument(
        "--source-password",
    )

    parser.add_argument(
        "--destination-username",
    )

    parser.add_argument(
        "--destination-password",
    )

    return parser.parse_args()


def main() -> None:
    """Run the recursive Girder folder transfer."""

    args = parse_arguments()

    print(
        "Connecting to source Girder instance...",
        flush=True,
    )

    gc_source = connect(
        args.source_api,
        api_key=args.source_api_key,
        username=args.source_username,
        password=args.source_password,
    )

    print(
        "Connecting to destination Girder instance...",
        flush=True,
    )

    gc_destination = connect(
        args.destination_api,
        api_key=args.destination_api_key,
        username=args.destination_username,
        password=args.destination_password,
    )

    source_folder = gc_source.getFolder(
        args.source_folder_id
    )

    print(
        "\nTransfer configuration",
        flush=True,
    )
    print(
        "----------------------",
        flush=True,
    )
    print(
        f"Source folder: {source_folder['name']}",
        flush=True,
    )
    print(
        f"Source folder ID: {args.source_folder_id}",
        flush=True,
    )
    print(
        "Destination parent ID: "
        f"{args.destination_parent_id}",
        flush=True,
    )
    print(
        "Destination parent type: "
        f"{args.destination_parent_type}",
        flush=True,
    )

    result = copy_folder_recursive(
        gc_source,
        gc_destination,
        args.source_folder_id,
        args.destination_parent_id,
        args.destination_parent_type,
    )

    print(
        "\nTransfer completed successfully.",
        flush=True,
    )
    print(
        f"Destination folder name: {result['name']}",
        flush=True,
    )
    print(
        f"Destination folder ID: {result['_id']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
