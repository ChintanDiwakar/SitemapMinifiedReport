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
from difflib import SequenceMatcher
import json

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
            
            return meta_info, html
    except Exception as e:
        st.error(f"Error extracting meta tags: {e}")
        return [], None

def extract_structured_data(html):
    """Extract JSON-LD structured data from HTML."""
    if not html:
        return []
    
    structured_data = []
    for script in html.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
            structured_data.append(data)
        except json.JSONDecodeError:
            continue
    
    return structured_data

def extract_page_elements(html):
    """Extract important page elements and their counts."""
    if not html:
        return {}
    
    elements = {}
    
    # Count headings
    for i in range(1, 7):
        elements[f'h{i}'] = len(html.css(f'h{i}'))
    
    # Count other important elements
    elements['img'] = len(html.css('img'))
    elements['a'] = len(html.css('a'))
    elements['p'] = len(html.css('p'))
    elements['ul'] = len(html.css('ul'))
    elements['ol'] = len(html.css('ol'))
    elements['div'] = len(html.css('div'))
    elements['form'] = len(html.css('form'))
    elements['iframe'] = len(html.css('iframe'))
    elements['script'] = len(html.css('script'))
    elements['style'] = len(html.css('style'))
    
    return elements

def extract_main_content(html):
    """Extract the main content text from HTML."""
    if not html:
        return ""
    
    # Try to find main content area
    content_selectors = ['main', 'article', '#content', '.content', '#main', '.main']
    
    for selector in content_selectors:
        content_area = html.css_first(selector)
        if content_area:
            # Remove script and style elements
            for script in content_area.css('script'):
                script.decompose()
            for style in content_area.css('style'):
                style.decompose()
            
            return content_area.text(strip=True)
    
    # If no content area found, extract body text
    body = html.css_first('body')
    if body:
        # Remove script and style elements
        for script in body.css('script'):
            script.decompose()
        for style in body.css('style'):
            style.decompose()
        
        return body.text(strip=True)
    
    return ""

def similar(a, b):
    """Calculate similarity ratio between two strings."""
    if not a or not b:
        return 0
    return SequenceMatcher(None, a, b).ratio()

async def analyze_single_url(url):
    """Analyze a single URL and gather comprehensive details."""
    results = {}
    
    # Start timing the overall analysis
    analysis_start = time.time()
    
    # 1. Extract all meta details and measure load time
    st.write(f"📋 Extracting meta tags for {url}...")
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
        
        # Extract structured data
        results["structured_data"] = extract_structured_data(html)
        
        # Extract page elements
        results["page_elements"] = extract_page_elements(html)
        
        # Extract main content
        results["main_content"] = extract_main_content(html)
    else:
        results["meta_tags"] = []
        results["structured_data"] = []
        results["page_elements"] = {}
        results["main_content"] = ""
    
    # 2. Generate QR codes for easy access
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
    
    # Display page elements
    st.write("### 📊 Page Elements")
    if results["page_elements"]:
        elements_df = pd.DataFrame([results["page_elements"]])
        st.dataframe(elements_df.T)
    else:
        st.warning("No page elements information available")

async def compare_multiple_urls(urls):
    """Compare multiple URLs (up to 5) for their meta details and content."""
    if not urls:
        st.error("No URLs provided for comparison.")
        return None, None
    
    # Create a progress container
    progress_container = st.empty()
    progress_container.info(f"Starting analysis of {len(urls)} URLs...")
    
    # Analyze each URL
    all_results = {}
    html_data = {}
    
    for i, url in enumerate(urls):
        progress_container.info(f"Analyzing URL {i+1}/{len(urls)}: {url}")
        
        # Fetch data
        response, desktop_load_time = await fetch_url_with_timing(url)
        meta_info, html = await extract_all_meta_tags(url)
        
        # Process results
        results = {
            "desktop_load_time": desktop_load_time,
            "mobile_load_time": desktop_load_time * 1.2,
            "googlebot_load_time": desktop_load_time * 0.9,
            "meta_tags": meta_info,
            "url_qr_code": generate_qr_code(url),
            "mobile_url": f"{url}?device=mobile",
            "mobile_qr_code": generate_qr_code(f"{url}?device=mobile"),
            "structured_data": extract_structured_data(html),
            "page_elements": extract_page_elements(html),
            "main_content": extract_main_content(html)
        }
        
        all_results[url] = results
        html_data[url] = html
    
    progress_container.success("All URLs analyzed successfully!")
    
    # Process the meta tags for comparison
    meta_comparison = {}
    
    # Define important meta tags to track
    common_meta_tags = [
        "title", "description", "keywords", "viewport", "robots", "canonical",
        "og:title", "og:description", "og:image", "og:url", "og:type", "og:site_name",
        "twitter:card", "twitter:title", "twitter:description", "twitter:image"
    ]
    
    # First, collect all meta tag names across all URLs
    all_meta_names = set()
    all_meta_properties = set()
    
    for url, results in all_results.items():
        for meta in results["meta_tags"]:
            if "name" in meta:
                all_meta_names.add(meta["name"])
            if "property" in meta:
                all_meta_properties.add(meta["property"])
    
    # Create a combined list of important meta tags to compare
    compare_meta_tags = list(common_meta_tags)
    for name in all_meta_names:
        if name not in compare_meta_tags:
            compare_meta_tags.append(name)
    for prop in all_meta_properties:
        if prop not in compare_meta_tags:
            compare_meta_tags.append(prop)
    
    # Now create a comparison dict for each URL
    for url, results in all_results.items():
        url_meta = {"load_time": f"{results['desktop_load_time']:.2f}s"}
        
        # Initialize with empty values
        for tag in compare_meta_tags:
            url_meta[tag] = ""
        
        # Fill in values from meta tags
        for meta in results["meta_tags"]:
            if "element" in meta and meta["element"] == "title":
                url_meta["title"] = meta.get("content", "")
            elif "name" in meta and meta["name"] in compare_meta_tags:
                url_meta[meta["name"]] = meta.get("content", "")
            elif "property" in meta and meta["property"] in compare_meta_tags:
                url_meta[meta["property"]] = meta.get("content", "")
        
        # Add page element counts
        for elem, count in results["page_elements"].items():
            url_meta[f"elements_{elem}"] = count
        
        meta_comparison[url] = url_meta
    
    # Create a comparison table
    comparison_df = pd.DataFrame.from_dict(meta_comparison, orient='index')
    
    # Perform content similarity analysis
    content_similarity = {}
    if len(urls) > 1:
        for i, url1 in enumerate(urls):
            for j, url2 in enumerate(urls):
                if i < j:  # Compare each pair once
                    content1 = all_results[url1]["main_content"]
                    content2 = all_results[url2]["main_content"]
                    
                    # Calculate similarity
                    sim_ratio = similar(content1, content2)
                    content_similarity[(url1, url2)] = sim_ratio
    
    # Return all results for detailed view
    return comparison_df, all_results, content_similarity

def display_comparison_results(comparison_df, all_results, content_similarity):
    """Display the enhanced comparison results with side-by-side analysis."""
    st.subheader("📊 URL Comparison Results")
    
    # Group meta tags into categories for better display
    meta_categories = {
        "Basic SEO": ["title", "description", "keywords", "robots", "canonical"],
        "Open Graph": [col for col in comparison_df.columns if col.startswith("og:")],
        "Twitter Cards": [col for col in comparison_df.columns if col.startswith("twitter:")],
        "Page Elements": [col for col in comparison_df.columns if col.startswith("elements_")],
        "Technical": ["viewport", "charset", "content-type", "load_time"]
    }
    
    # Create a more visual comparison using tabs for different categories
    st.write("### Side-by-Side Meta Tag Comparison")
    
    meta_tabs = st.tabs(list(meta_categories.keys()))
    
    # For each category, display a side-by-side comparison
    for i, (category, fields) in enumerate(meta_categories.items()):
        with meta_tabs[i]:
            # Filter the columns that exist in our dataframe
            available_fields = [field for field in fields if field in comparison_df.columns]
            
            if available_fields:
                category_df = comparison_df[available_fields]
                
                # Transpose for better side-by-side comparison
                st.dataframe(category_df.T, use_container_width=True)
                
                # Highlight differences
                for field in available_fields:
                    if field in comparison_df.columns:
                        values = comparison_df[field].unique()
                        if len(values) > 1 and not all(pd.isna(v) for v in values):
                            st.warning(f"⚠️ Inconsistent {field} values across URLs")
            else:
                st.info(f"No {category} tags found for comparison")
    
    # Display content similarity matrix
    if content_similarity:
        st.write("### 📝 Content Similarity Analysis")
        st.write("This shows how similar the main content is between each pair of URLs (1.0 = identical)")
        
        # Create a nice visual similarity matrix
        similarity_data = []
        for (url1, url2), similarity in content_similarity.items():
            similarity_data.append({
                "URL 1": url1,
                "URL 2": url2,
                "Similarity": similarity,
                "Visual": "🟩" * int(similarity * 10) + "⬜" * (10 - int(similarity * 10))
            })
        
        similarity_df = pd.DataFrame(similarity_data)
        st.dataframe(similarity_df, use_container_width=True)
    
    # Allow downloading comparison as CSV
    csv = comparison_df.to_csv(index=True).encode('utf-8')
    st.download_button("Download Comparison CSV", csv, "url_comparison.csv", "text/csv")
    
    # Display load time comparison
    st.write("### ⏱️ Load Time Comparison")
    
    load_times = {}
    for url, results in all_results.items():
        load_times[url] = results["desktop_load_time"]
    
    # Sort by load time
    sorted_urls = sorted(load_times.items(), key=lambda x: x[1])
    
    # Create a bar chart
    load_time_df = pd.DataFrame({
        'URL': [url for url, _ in sorted_urls],
        'Load Time (s)': [time for _, time in sorted_urls]
    })
    
    st.bar_chart(load_time_df.set_index('URL'))
    
    # Display detailed results for each URL
    st.write("### 🔍 Detailed Element Counts")
    
    # Create a DataFrame with element counts for each URL
    element_counts = {}
    for url, results in all_results.items():
        element_counts[url] = results["page_elements"]
    
    element_df = pd.DataFrame(element_counts)
    st.dataframe(element_df)
    
    # Display tabs for each URL's full details
    st.write("### 📑 Individual URL Details")
    
    tabs = st.tabs([f"URL {i+1}" for i in range(len(all_results))])
    
    for i, (tab, (url, results)) in enumerate(zip(tabs, all_results.items())):
        with tab:
            st.subheader(f"URL {i+1}: {url}")
            
            # Show QR code
            col1, col2 = st.columns(2)
            with col1:
                st.write("#### QR Code")
                st.image(f"data:image/png;base64,{results['url_qr_code']}", width=200)
            
            with col2:
                st.write("#### Key Metrics")
                st.metric("Load Time", f"{results['desktop_load_time']:.2f}s")
                st.metric("Element Count", sum(results['page_elements'].values()))
            
            # Show meta tags
            with st.expander("Meta Tags"):
                if results["meta_tags"]:
                    meta_df = pd.DataFrame(results["meta_tags"])
                    st.dataframe(meta_df)
                else:
                    st.warning("No meta tags found")
            
            # Show structured data
            with st.expander("Structured Data"):
                if results["structured_data"]:
                    st.json(results["structured_data"])
                else:
                    st.warning("No structured data found")

def main():
    st.title("Fast Sitemap Checker")

    # Sidebar for navigation
    option = st.sidebar.radio("Select Functionality", [
        "🔍 Search URL in Sitemap", 
        "✅ Check All URLs", 
        "🔎 Single URL Analysis",
        "🔄 Compare URLs"
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
                st.download_button("Download CSV", csv, "sitemap_report.csv", "text/csv")
    
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
    
    elif option == "🔄 Compare URLs":
        st.subheader("🔄 Compare Multiple URLs Side by Side")
        st.write("Enter up to 5 URLs to compare their content, structure, elements, and meta tags")
        
        # Create input fields for up to 5 URLs
        urls = []
        for i in range(5):
            url = st.text_input(f"URL {i+1}:", key=f"compare_url_{i}")
            if url:
                urls.append(url)
        
        # Add checkbox to enable similar content detection
        content_similarity_enabled = st.checkbox("Enable content similarity analysis", value=True)
        
        if st.button("Compare URLs Side by Side"):
            if not urls:
                st.error("Please enter at least one URL to compare")
                return
            
            if any(not url.startswith(("http://", "https://")) for url in urls):
                st.error("All URLs must start with http:// or https://")
                return
            
            with st.spinner(f"Comparing {len(urls)} URLs... This may take a few minutes."):
                # Run the comparison analysis
                comparison_df, all_results, content_similarity = asyncio.run(compare_multiple_urls(urls))
                
                # Display the comparison results
                display_comparison_results(comparison_df, all_results, content_similarity if content_similarity_enabled else {})
