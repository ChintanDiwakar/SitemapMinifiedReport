import streamlit as st
import httpx
import pandas as pd
from selectolax.parser import HTMLParser
import xml.etree.ElementTree as ET
import asyncio
import time
import re
import base64
from datetime import datetime
import urllib.parse
import qrcode
from io import BytesIO
import difflib
import os
from pathlib import Path

LOCALE_PATHS = ["/ru/", "/zh-cn/", "/de/", "/fr/", "/ar/"]

async def fetch_sitemap_urls(sitemap_url):
    """Fetch and parse XML sitemap to extract all URLs asynchronously, ignoring locale-specific URLs."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(sitemap_url, timeout=30, follow_redirects=True)
            if response.status_code != 200:
                st.error(f"Failed to fetch sitemap. Status Code: {response.status_code}")
                return []
            
            root = ET.fromstring(response.content)
            namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            
            urls = [elem.text for elem in root.findall('.//ns:loc', namespaces)]
            filtered_urls = [url for url in urls if not any(locale in url for locale in LOCALE_PATHS)]
            return filtered_urls
    except Exception as e:
        st.error(f"Error fetching sitemap: {e}")
        return []

async def fetch_url_details(url, client, retries=3):
    """Fetch URL status code, meta title, and description asynchronously with retries."""
    for attempt in range(retries):
        try:
            response = await client.get(url, timeout=10, follow_redirects=True)
            if response.status_code != 200:
                return url, response.status_code, "Error", "Failed to load", "N/A"
            
            html = HTMLParser(response.text)
            title = html.css_first("title").text(strip=True) if html.css_first("title") else "N/A"
            meta_desc = html.css_first("meta[name='description']")
            description = meta_desc.attrs.get("content", "N/A") if meta_desc else "N/A"
            site_name = html.css_first("meta[property='og:site_name']")
            site_name = site_name.attrs.get("content", "N/A") if site_name else "N/A"
            
            return url, response.status_code, title, description, site_name

        except httpx.RequestError as e:
            if attempt < retries - 1:
                await asyncio.sleep(2)
            else:
                return url, "Failed", f"Error: {str(e)[:50]}...", "N/A", "N/A"

def generate_qr_code(url):
    """Generate a QR code for the URL."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered)
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return img_str

def scan_directory(directory_path):
    """Scan a directory and return all files with their metadata."""
    files = []
    try:
        for root, _, filenames in os.walk(directory_path):
            for filename in filenames:
                file_path = os.path.join(root, filename)
                file_info = {
                    "path": file_path,
                    "name": filename,
                    "extension": os.path.splitext(filename)[1].lower(),
                    "size": os.path.getsize(file_path),
                    "modified": datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S'),
                    "created": datetime.fromtimestamp(os.path.getctime(file_path)).strftime('%Y-%m-%d %H:%M:%S'),
                }
                files.append(file_info)
    except Exception as e:
        st.error(f"Error scanning directory: {e}")
    return files

def find_similar_files(files, similarity_threshold=0.7):
    """Find files with similar names."""
    similar_groups = []
    processed = set()
    
    for i, file1 in enumerate(files):
        if file1["path"] in processed:
            continue
        
        group = [file1]
        processed.add(file1["path"])
        
        for j, file2 in enumerate(files):
            if i == j or file2["path"] in processed:
                continue
            
            # Compare filenames (without extension)
            name1 = os.path.splitext(file1["name"])[0]
            name2 = os.path.splitext(file2["name"])[0]
            
            similarity = difflib.SequenceMatcher(None, name1, name2).ratio()
            
            if similarity >= similarity_threshold:
                group.append(file2)
                processed.add(file2["path"])
        
        if len(group) > 1:
            similar_groups.append(group)
    
    return similar_groups

def compare_file_content(file1_path, file2_path):
    """Compare the content of two files and return a diff."""
    try:
        with open(file1_path, 'r', encoding='utf-8') as f1, open(file2_path, 'r', encoding='utf-8') as f2:
            file1_lines = f1.readlines()
            file2_lines = f2.readlines()
            
        diff = list(difflib.unified_diff(
            file1_lines, 
            file2_lines,
            fromfile=os.path.basename(file1_path),
            tofile=os.path.basename(file2_path),
            lineterm=''
        ))
        
        return diff
    except UnicodeDecodeError:
        # If files are not text files
        return ["Binary files cannot be compared line by line."]
    except Exception as e:
        return [f"Error comparing files: {str(e)}"]

def read_file_preview(file_path, max_lines=20):
    """Read a preview of the file content."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    lines.append("...(more lines)...")
                    break
                lines.append(line)
            return "".join(lines)
    except UnicodeDecodeError:
        return "Binary file - preview not available."
    except Exception as e:
        return f"Error reading file: {str(e)}"

def compare_meta_properties(file_paths):
    """Compare metadata properties of multiple files."""
    meta_data = []
    for path in file_paths:
        file_info = Path(path)
        stats = file_info.stat()
        meta = {
            "path": str(file_info),
            "name": file_info.name,
            "size": stats.st_size,
            "modified": datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            "created": datetime.fromtimestamp(stats.st_ctime).strftime('%Y-%m-%d %H:%M:%S'),
            "is_directory": file_info.is_dir(),
            "extension": file_info.suffix,
            "parent": str(file_info.parent),
        }
        meta_data.append(meta)
    
    return pd.DataFrame(meta_data)

def main():
    st.title("File Comparison Tool")

    # Sidebar for navigation
    option = st.sidebar.radio("Select Functionality", [
        "🔍 Find Similar Files",
        "📊 Compare Files Side by Side",
        "📡 Sitemap Checker"
    ])

    if option == "🔍 Find Similar Files":
        st.subheader("🔍 Find Files with Similar Names")
        
        directory_path = st.text_input("Enter Directory Path to Scan:", ".")
        similarity_threshold = st.slider("Similarity Threshold", min_value=0.1, max_value=1.0, value=0.7, step=0.05)
        
        if st.button("Scan Directory"):
            if not os.path.isdir(directory_path):
                st.error(f"Invalid directory path: {directory_path}")
                return
            
            with st.spinner("Scanning directory..."):
                files = scan_directory(directory_path)
                if not files:
                    st.warning("No files found in the directory.")
                    return
                
                st.success(f"Found {len(files)} files.")
                
                # Find similar files
                similar_groups = find_similar_files(files, similarity_threshold)
                
                if not similar_groups:
                    st.info("No similar files found with the current threshold.")
                else:
                    st.write(f"Found {len(similar_groups)} groups of similar files:")
                    
                    for i, group in enumerate(similar_groups):
                        with st.expander(f"Group {i+1} ({len(group)} files)"):
                            files_df = pd.DataFrame(group)
                            st.dataframe(files_df[["name", "size", "modified", "path"]])
                            
                            if st.button(f"Compare Files in Group {i+1}", key=f"compare_group_{i}"):
                                st.session_state.selected_files = [file["path"] for file in group]
                                st.session_state.current_option = "📊 Compare Files Side by Side"
                                st.experimental_rerun()

    elif option == "📊 Compare Files Side by Side":
        st.subheader("📊 Compare Files Side by Side")
        
        # Initialize session state for selected files if not exists
        if "selected_files" not in st.session_state:
            st.session_state.selected_files = []
        
        # Allow user to select files
        file_selection_method = st.radio("Select files by:", ("Manual Input", "File Upload"))
        
        selected_files = []
        
        if file_selection_method == "Manual Input":
            # Display current selected files
            if st.session_state.selected_files:
                st.write("Currently selected files:")
                for i, file in enumerate(st.session_state.selected_files):
                    st.text(f"{i+1}. {file}")
                
                if st.button("Clear Selection"):
                    st.session_state.selected_files = []
                    st.experimental_rerun()
            
            # Let user add new files
            new_file = st.text_input("Enter File Path:")
            if st.button("Add File") and new_file:
                if os.path.isfile(new_file):
                    st.session_state.selected_files.append(new_file)
                    st.success(f"Added: {new_file}")
                    st.experimental_rerun()
                else:
                    st.error(f"File not found: {new_file}")
            
            selected_files = st.session_state.selected_files
        
        else:  # File Upload
            uploaded_files = st.file_uploader("Upload files to compare", accept_multiple_files=True)
            if uploaded_files:
                # Save uploaded files to temp directory
                for uploaded_file in uploaded_files:
                    with open(f"/tmp/{uploaded_file.name}", "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    selected_files.append(f"/tmp/{uploaded_file.name}")
        
        if len(selected_files) < 2:
            st.warning("Please select at least 2 files to compare.")
        else:
            st.success(f"Comparing {len(selected_files)} files.")
            
            # Create tabs for different comparison views
            content_tab, meta_tab, diff_tab = st.tabs(["Content View", "Metadata Comparison", "Differences"])
            
            with content_tab:
                st.subheader("File Content")
                file_tabs = st.tabs([os.path.basename(file) for file in selected_files])
                
                for i, (tab, file_path) in enumerate(zip(file_tabs, selected_files)):
                    with tab:
                        st.text(f"File: {file_path}")
                        preview = read_file_preview(file_path)
                        st.code(preview)
            
            with meta_tab:
                st.subheader("File Metadata Comparison")
                meta_df = compare_meta_properties(selected_files)
                st.dataframe(meta_df)
                
                # Allow downloading meta comparison as CSV
                csv = meta_df.to_csv(index=False).encode('utf-8')
                st.download_button("Download Metadata CSV", csv, "file_metadata_comparison.csv", "text/csv")
            
            with diff_tab:
                st.subheader("File Differences")
                
                if len(selected_files) == 2:
                    # Direct comparison of 2 files
                    diff = compare_file_content(selected_files[0], selected_files[1])
                    st.code("\n".join(diff))
                else:
                    # For more than 2 files, let user select pairs to compare
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        file1_idx = st.selectbox("Select File 1:", range(len(selected_files)), format_func=lambda i: os.path.basename(selected_files[i]))
                    
                    with col2:
                        file2_idx = st.selectbox("Select File 2:", range(len(selected_files)), format_func=lambda i: os.path.basename(selected_files[i]))
                    
                    if file1_idx != file2_idx:
                        diff = compare_file_content(selected_files[file1_idx], selected_files[file2_idx])
                        st.code("\n".join(diff))
                    else:
                        st.warning("Please select different files to compare.")

    elif option == "📡 Sitemap Checker":
        st.subheader("📡 Sitemap Checker")
        
        sitemap_url = st.text_input("Enter Sitemap URL:", "https://www.example.com/sitemap.xml")
        
        if st.button("Fetch Sitemap"):
            with st.spinner("Fetching Sitemap URLs..."):
                urls = asyncio.run(fetch_sitemap_urls(sitemap_url))

                if not urls:
                    st.error("No URLs found in the sitemap.")
                    return
                
                st.success(f"Found {len(urls)} URLs in the sitemap.")
                
                # Display the URLs
                urls_df = pd.DataFrame({"URL": urls})
                st.dataframe(urls_df)
                
                # Allow downloading URLs as CSV
                csv = urls_df.to_csv(index=False).encode('utf-8')
                st.download_button("Download URLs CSV", csv, "sitemap_urls.csv", "text/csv")
                
                # Generate QR codes for a few example URLs
                st.subheader("Sample QR Codes")
                if len(urls) > 0:
                    sample_size = min(3, len(urls))
                    sample_urls = urls[:sample_size]
                    
                    cols = st.columns(sample_size)
                    for i, (col, url) in enumerate(zip(cols, sample_urls)):
                        with col:
                            qr_code = generate_qr_code(url)
                            st.image(f"data:image/png;base64,{qr_code}", caption=f"URL {i+1}", width=200)
                            st.markdown(f"[{url}]({url})")

if __name__ == "__main__":
    main()
