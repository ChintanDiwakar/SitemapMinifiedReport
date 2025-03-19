import streamlit as st
import httpx
import pandas as pd
from selectolax.parser import HTMLParser
import xml.etree.ElementTree as ET
import asyncio
import time
import re

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

def main():
    st.title("Fast Sitemap Checker")

    # Sidebar for navigation
    option = st.sidebar.radio("Select Functionality", ["🔍 Search URL in Sitemap", "✅ Check All URLs"])

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

if __name__ == "__main__":
    main()
