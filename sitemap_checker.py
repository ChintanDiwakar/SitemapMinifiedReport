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

async def process_urls_in_batches(urls, batch_size=100, max_concurrent=50):
    """Process URLs in batches asynchronously."""
    results = []
    total_urls = len(urls)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    eta_text = st.empty()
    start_time = time.time()
    
    for batch_start in range(0, total_urls, batch_size):
        batch_end = min(batch_start + batch_size, total_urls)
        batch = urls[batch_start:batch_end]
        
        async with httpx.AsyncClient(limits=httpx.Limits(max_connections=max_concurrent)) as client:
            tasks = [fetch_url_details(url, client) for url in batch]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
        
        completed = batch_end
        progress = completed / total_urls
        progress_bar.progress(progress)
        
        elapsed_time = time.time() - start_time
        urls_per_second = completed / elapsed_time if elapsed_time > 0 else 0
        remaining_urls = total_urls - completed
        remaining_seconds = remaining_urls / urls_per_second if urls_per_second > 0 else 0
        
        eta_minutes, eta_seconds = divmod(int(remaining_seconds), 60)
        
        status_text.write(f"Processed {completed}/{total_urls} URLs")
        eta_text.write(f"⏳ ETA: {eta_minutes}m {eta_seconds}s | ✅ Completed: {completed} | ❌ Pending: {remaining_urls} | Speed: {urls_per_second:.1f} URLs/sec")
    
    return results

def filter_urls_by_regex(urls, regex_pattern):
    """Filter URLs based on regex pattern."""
    if not regex_pattern:
        return urls
    
    try:
        pattern = re.compile(regex_pattern)
        filtered_urls = [url for url in urls if pattern.search(url)]
        return filtered_urls
    except re.error as e:
        st.error(f"Invalid regex pattern: {e}")
        return urls

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

async def fetch_url_with_timing(url):
    """Fetch URL and measure load time."""
    start_time = time.time()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30, follow_redirects=True)
            load_time = time.time() - start_time
            return response, load_time
    except Exception as e:
        load_time = time.time() - start_time
        st.error(f"Error fetching URL: {e}")
        return None, load_time

async def extract_all_meta_tags(url):
    """Extract all meta tags from a URL."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30, follow_redirects=True)
            if response.status_code != 200:
                return []
            
            html = HTMLParser(response.text)
            meta_tags = html.css("meta")
            
            meta_info = []
            for tag in meta_tags:
                attributes = tag.attributes
                meta_data = {}
                for attr, value in attributes.items():
                    meta_data[attr] = value
                meta_info.append(meta_data)
            
            # Also extract other important head elements
            title = html.css_first("title")
            if title:
                meta_info.append({"element": "title", "content": title.text(strip=True)})
                
            links = html.css("link[rel]")
            for link in links:
                link_data = {"element": "link"}
                for attr, value in link.attributes.items():
                    link_data[attr] = value
                meta_info.append(link_data)
            
            return meta_info
    except Exception as e:
        st.error(f"Error extracting meta tags: {e}")
        return []

async def analyze_single_url(url):
    """Analyze a single URL and gather comprehensive details."""
    results = {}
    
    # Start timing the overall analysis
    analysis_start = time.time()
    
    # 1. Extract all meta details and measure load time
    st.write("📋 Extracting meta tags and measuring load time...")
    response, desktop_load_time = await fetch_url_with_timing(url)
    results["desktop_load_time"] = desktop_load_time
    
    # Only proceed if we got a response
    if response and response.status_code == 200:
        # Extract meta tags from the response
        html = HTMLParser(response.text)
        meta_tags = html.css("meta")
        
        meta_info = []
        for tag in meta_tags:
            attributes = tag.attributes
            meta_data = {}
            for attr, value in attributes.items():
                meta_data[attr] = value
            meta_info.append(meta_data)
        
        # Also extract other important head elements
        title = html.css_first("title")
        if title:
            meta_info.append({"element": "title", "content": title.text(strip=True)})
            
        links = html.css("link[rel]")
        for link in links:
            link_data = {"element": "link"}
            for attr, value in link.attributes.items():
                link_data[attr] = value
            meta_info.append(link_data)
        
        results["meta_tags"] = meta_info
    else:
        results["meta_tags"] = []
    
    # 2. Generate QR codes for easy access
    st.write("🔎 Generating QR codes...")
    results["url_qr_code"] = generate_qr_code(url)
    
    # 3. Extract additional device-specific information if available
    mobile_url = f"{url}?device=mobile"
    results["mobile_url"] = mobile_url
    results["mobile_qr_code"] = generate_qr_code(mobile_url)
    
    # Use estimated values for mobile/googlebot since we can't directly measure
    results["mobile_load_time"] = desktop_load_time * 1.2  # Estimate: mobile is ~20% slower
    results["googlebot_load_time"] = desktop_load_time * 0.9  # Estimate: googlebot might be a bit faster
    
    # Calculate overall analysis time
    results["total_analysis_time"] = time.time() - analysis_start
    
    return results

def display_url_analysis(url, results):
    """Display the comprehensive URL analysis results."""
    st.subheader(f"📊 Analysis Results for {url}")
    
    # Display load times
    st.write("### ⏱️ Load Times")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Desktop Load Time", f"{results['desktop_load_time']:.2f}s")
    with col2:
        st.metric("Mobile Load Time (est.)", f"{results['mobile_load_time']:.2f}s")
    with col3:
        st.metric("Googlebot Load Time (est.)", f"{results['googlebot_load_time']:.2f}s")
    
    st.info(f"Total analysis completed in {results['total_analysis_time']:.2f} seconds")
    
    # Display QR codes for easy access
    st.write("### 📱 Quick Access QR Codes")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Desktop View")
        st.markdown(f"Scan to view: {url}")
        st.image(f"data:image/png;base64,{results['url_qr_code']}", width=300)
    
    with col2:
        st.subheader("Mobile View")
        st.markdown(f"Scan to view: {results['mobile_url']}")
        st.image(f"data:image/png;base64,{results['mobile_qr_code']}", width=300)
    
    # Display meta tags
    st.write("### 🏷️ Meta Tags")
    if results["meta_tags"]:
        meta_df = pd.DataFrame(results["meta_tags"])
        st.dataframe(meta_df)
        
        # Allow downloading meta tags as CSV
        csv = meta_df.to_csv(index=False).encode('utf-8')
        st.download_button("Download Meta Tags CSV", csv, f"meta_tags_{url.replace('://', '_').replace('/', '_')}.csv", "text/csv")
    else:
        st.warning("No meta tags found")

def main():
    st.title("Fast Sitemap Checker")

    # Sidebar for navigation
    option = st.sidebar.radio("Select Functionality", [
        "🔍 Search URL in Sitemap", 
        "✅ Check All URLs", 
        "🔎 Single URL Analysis"
    ])

    if option in ["🔍 Search URL in Sitemap", "✅ Check All URLs"]:
        sitemap_url = st.text_input("Enter Sitemap URL:", "https://www.profoundproperties.com/sitemap.xml")

    if option == "🔍 Search URL in Sitemap":
        st.subheader("🔍 Search for a Specific URL in the Sitemap")

        check_url = st.text_input("Enter URL to search:", "https://www.profoundproperties.com/")

        if st.button("Search in Sitemap"):
            with st.spinner("Fetching Sitemap URLs..."):
                urls = asyncio.run(fetch_sitemap_urls(sitemap_url))

                if not urls:
                    st.error("No URLs found in the sitemap.")
                    return

                if check_url in urls:
                    st.success(f"✅ URL {check_url} **exists** in the sitemap.")
                else:
                    st.error(f"❌ URL {check_url} **not found** in the sitemap.")

    elif option == "✅ Check All URLs":
        st.subheader("✅ Check the Status of All URLs in Sitemap")

        col1, col2 = st.columns(2)
        with col1:
            batch_size = st.number_input("Batch Size", min_value=10, max_value=500, value=100)
        with col2:
            max_concurrent = st.number_input("Max Concurrent Requests", min_value=10, max_value=100, value=50)
        
        # Add regex filter input
        regex_pattern = st.text_input(
            "Filter URLs by Regex Pattern (leave empty to check all):", 
            "", 
            help="Only URLs matching this pattern will be checked. Example: '/properties/' will only check URLs containing '/properties/'"
        )
        
        # Add option to test regex pattern
        if regex_pattern and st.button("Test Regex Pattern"):
            try:
                pattern = re.compile(regex_pattern)
                st.success(f"✅ Valid regex pattern: `{regex_pattern}`")
                
                # Show example matches with the pattern
                test_url = "https://www.profoundproperties.com/properties/villa-123"
                if pattern.search(test_url):
                    st.info(f"Example: Pattern would match URL like `{test_url}`")
                else:
                    st.info(f"Example: Pattern would NOT match URL like `{test_url}`")
            except re.error as e:
                st.error(f"❌ Invalid regex pattern: {e}")

        if st.button("Start Checking URLs"):
            with st.spinner("Fetching Sitemap URLs..."):
                all_urls = asyncio.run(fetch_sitemap_urls(sitemap_url))

                if not all_urls:
                    st.error("No URLs found in the sitemap.")
                    return

                st.info(f"Found {len(all_urls)} URLs (excluding locales) in the sitemap.")
                
                # Apply regex filtering if provided
                filtered_urls = filter_urls_by_regex(all_urls, regex_pattern)
                
                if regex_pattern:
                    st.info(f"Filtered to {len(filtered_urls)} URLs matching pattern: `{regex_pattern}`")
                    if len(filtered_urls) == 0:
                        st.warning("No URLs match the given regex pattern. Please check your pattern and try again.")
                        return
                
                st.info("🚀 Starting URL status check...")

                results = asyncio.run(process_urls_in_batches(filtered_urls, batch_size, max_concurrent))

                df = pd.DataFrame(results, columns=["URL", "Status Code", "Meta Title", "Meta Description", "Site Name"])

                # Add filtering options
                status_filter = st.multiselect("Filter by Status Code:", df["Status Code"].unique(), default=[200, 404])
                filtered_df = df[df["Status Code"].isin(status_filter)]
                
                # Show the results
                st.write(f"Results: {len(filtered_df)} URLs")
                st.dataframe(filtered_df)

                csv = filtered_df.to_csv(index=False).encode('utf-8')
                st.download_button("Download CSV", csv, "sitemap_report.csv", "text/csv", key="download-csv")
    
    elif option == "🔎 Single URL Analysis":
        st.subheader("🔎 Comprehensive Single URL Analysis")
        st.write("Enter a URL to analyze its meta tags, get QR codes for easy access, and measure load times")
        
        analyze_url = st.text_input("Enter URL to analyze:", "https://www.example.com/")
        
        if st.button("Analyze URL"):
            if not analyze_url.startswith(("http://", "https://")):
                st.error("Please enter a valid URL starting with http:// or https://")
                return
            
            with st.spinner(f"Analyzing {analyze_url}... This may take a minute."):
                # Run the comprehensive analysis
                results = asyncio.run(analyze_single_url(analyze_url))
                
                # Display the results
                display_url_analysis(analyze_url, results)

if __name__ == "__main__":
    main()
