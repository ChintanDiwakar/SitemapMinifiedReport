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

async def extract_page_elements(url):
    """Extract common HTML elements and their count."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30, follow_redirects=True)
            if response.status_code != 200:
                return {}
            
            html = HTMLParser(response.text)
            elements = {}
            
            # Extract count of common HTML elements
            elements["h1"] = len(html.css("h1"))
            elements["h2"] = len(html.css("h2"))
            elements["h3"] = len(html.css("h3"))
            elements["p"] = len(html.css("p"))
            elements["a"] = len(html.css("a"))
            elements["img"] = len(html.css("img"))
            elements["ul"] = len(html.css("ul"))
            elements["ol"] = len(html.css("ol"))
            elements["div"] = len(html.css("div"))
            elements["form"] = len(html.css("form"))
            elements["iframe"] = len(html.css("iframe"))
            
            return elements
    except Exception as e:
        st.error(f"Error extracting page elements: {e}")
        return {}

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
        
        # Extract page elements
        elements = {
            "h1": len(html.css("h1")),
            "h2": len(html.css("h2")),
            "h3": len(html.css("h3")),
            "p": len(html.css("p")),
            "a": len(html.css("a")),
            "img": len(html.css("img")),
            "ul": len(html.css("ul")),
            "ol": len(html.css("ol")),
            "div": len(html.css("div")),
            "form": len(html.css("form")),
            "iframe": len(html.css("iframe"))
        }
        results["page_elements"] = elements
    else:
        results["meta_tags"] = []
        results["page_elements"] = {}
    
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
    """Compare multiple URLs in a single table format."""
    if not urls:
        st.error("No URLs provided for comparison.")
        return None, None
    
    # Create a progress container
    progress_container = st.empty()
    progress_container.info(f"Starting analysis of {len(urls)} URLs...")
    
    # Analyze each URL
    all_results = {}
    
    for i, url in enumerate(urls):
        progress_container.info(f"Analyzing URL {i+1}/{len(urls)}: {url}")
        results = await analyze_single_url(url)
        all_results[url] = results
    
    progress_container.success("All URLs analyzed successfully!")
    
    # Process the meta tags for comparison
    meta_comparison = {}
    
    # Important meta tags to track
    important_meta_tags = [
        "title", "description", "keywords", "viewport", "robots", "canonical",
        "og:title", "og:description", "og:image", "og:url", "og:type", "og:site_name",
        "twitter:card", "twitter:title", "twitter:description", "twitter:image"
    ]
    
    # Collect all unique meta tag names across all URLs
    all_meta_names = set()
    all_meta_properties = set()
    
    for url, results in all_results.items():
        for meta in results["meta_tags"]:
            if "name" in meta:
                all_meta_names.add(meta["name"])
            if "property" in meta:
                all_meta_properties.add(meta["property"])
    
    # Create a comprehensive table with all meta information
    comparison_data = []
    
    # For each URL, extract key metrics and meta tags
    for url, results in all_results.items():
        url_short = url.replace("https://", "").replace("http://", "").split("/")[0]
        
        # Basic URL info
        row = {
            "URL": url,
            "Display Name": url_short,
            "Load Time (s)": round(results["desktop_load_time"], 2)
        }
        
        # Extract meta tags
        meta_dict = {}
        for meta in results["meta_tags"]:
            if "element" in meta and meta["element"] == "title":
                meta_dict["title"] = meta.get("content", "")
            elif "name" in meta:
                meta_dict[meta["name"]] = meta.get("content", "")
            elif "property" in meta:
                meta_dict[meta["property"]] = meta.get("content", "")
        
        # Add important meta tags to the row
        for tag in important_meta_tags:
            row[f"Meta: {tag}"] = meta_dict.get(tag, "")
        
        # Add page element counts
        for elem, count in results["page_elements"].items():
            row[f"Element: {elem}"] = count
        
        comparison_data.append(row)
    
    # Create a single comprehensive comparison table
    comparison_df = pd.DataFrame(comparison_data)
    
    return comparison_df, all_results

def display_comparison_in_single_table(comparison_df, all_results):
    """Display the comparison results in a single comprehensive table."""
    st.subheader("📊 URL Comparison Results")
    
    # Create categories for organize the comparison
    categories = [
        {"name": "Basic Info", "prefix": "", "columns": ["URL", "Display Name", "Load Time (s)"]},
        {"name": "SEO Meta Tags", "prefix": "Meta: ", "columns": ["Meta: title", "Meta: description", "Meta: keywords", "Meta: robots", "Meta: canonical"]},
        {"name": "Open Graph", "prefix": "Meta: og:", "columns": [col for col in comparison_df.columns if col.startswith("Meta: og:")]},
        {"name": "Twitter Cards", "prefix": "Meta: twitter:", "columns": [col for col in comparison_df.columns if col.startswith("Meta: twitter:")]},
        {"name": "HTML Elements", "prefix": "Element: ", "columns": [col for col in comparison_df.columns if col.startswith("Element: ")]}
    ]
    
    # Display URL comparison in a single table with all data
    st.write("### 📑 Complete URL Comparison")
    
    # First display a basic URL info table
    st.write("#### Basic Information")
    basic_cols = ["URL", "Display Name", "Load Time (s)"]
    basic_df = comparison_df[basic_cols].copy()
    st.dataframe(basic_df)
    
    # Comprehensive side-by-side comparison table
    st.write("#### Side-by-Side Comparison")
    
    # Reshape the data for easier comparison - pivot the table
    # First create a unique identifier for each URL
    comparison_df['URL_ID'] = comparison_df['Display Name']
    
    # For each category, create a pivot table
    for category in categories:
        if category["name"] == "Basic Info":
            continue  # Skip basic info as we already displayed it
            
        st.write(f"##### {category['name']}")
        
        # Get the columns for this category
        category_cols = [col for col in category["columns"] if col in comparison_df.columns]
        
        if category_cols:
            # Create a subset dataframe with just these columns
            subset_df = comparison_df[["URL_ID"] + category_cols].copy()
            
            # Remove the prefix from column names for cleaner display
            for col in category_cols:
                if category["prefix"] and col.startswith(category["prefix"]):
                    new_col = col.replace(category["prefix"], "")
                    subset_df = subset_df.rename(columns={col: new_col})
            
            # Set URL_ID as index for better display
            subset_df = subset_df.set_index("URL_ID")
            
            # Display the category-specific comparison table
            st.dataframe(subset_df)
            
            # Check for inconsistencies
            for col in category_cols:
                cleaned_col = col.replace(category["prefix"], "")
                values = comparison_df[col].dropna().unique()
                if len(values) > 1:
                    st.warning(f"⚠️ Inconsistent '{cleaned_col}' values detected")
        else:
            st.info(f"No {category['name']} found for comparison")
    
    # Allow downloading the full comparison table as CSV
    csv = comparison_df.to_csv(index=False).encode('utf-8')
    st.download_button("Download Full Comparison CSV", csv, "url_comparison.csv", "text/csv")
    
    # Display a visual load time comparison
    st.write("### ⏱️ Load Time Comparison")
    
    # Create a bar chart for load times
    load_time_df = comparison_df[["Display Name", "Load Time (s)"]].copy()
    load_time_df = load_time_df.sort_values("Load Time (s)")
    
    st.bar_chart(load_time_df.set_index("Display Name"))
    
    # Element count comparison
    st.write("### 📊 HTML Element Comparison")
    
    # Get all element columns
    element_cols = [col for col in comparison_df.columns if col.startswith("Element: ")]
    
    if element_cols:
        # Create a subset with just element counts
        element_df = comparison_df[["Display Name"] + element_cols].copy()
        
        # Clean column names
        for col in element_cols:
            new_col = col.replace("Element: ", "")
            element_df = element_df.rename(columns={col: new_col})
        
        # Set URL as index
        element_df = element_df.set_index("Display Name")
        
        # Display the element comparison
        st.dataframe(element_df)
    else:
        st.info("No element count data available for comparison")

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
    
    elif option == "🔄 Compare URLs":
        st.subheader("🔄 Side-by-Side URL Comparison")
        st.write("Enter up to 5 URLs to compare them side by side in a comprehensive table")
        
        # Create input fields for up to 5 URLs
        urls = []
        for i in range(5):
            url = st.text_input(f"URL {i+1}:", key=f"compare_url_{i}")
            if url:
                urls.append(url)
        
        if st.button("Compare URLs Side by Side"):
            if not urls:
                st.error("Please enter at least one URL to compare")
                return
            
            if any(not url.startswith(("http://", "https://")) for url in urls):
                st.error("All URLs must start with http:// or https://")
                return
            
            with st.spinner(f"Comparing {len(urls)} URLs... This may take a few minutes."):
                # Run the comparison analysis
                comparison_df, all_results = asyncio.run(compare_multiple_urls(urls))
                
                # Display the comparison results in a single table
                display_comparison_in_single_table(comparison_df, all_results)

if __name__ == "__main__":
    main()
