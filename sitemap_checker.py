import streamlit as st
import httpx
import pandas as pd
from selectolax.parser import HTMLParser
import xml.etree.ElementTree as ET
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial


async def fetch_sitemap_urls(sitemap_url):
    """Fetch and parse XML sitemap to extract all URLs asynchronously."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(sitemap_url, timeout=30, follow_redirects=True)
            if response.status_code != 200:
                st.error(f"Failed to fetch sitemap. Status Code: {response.status_code}")
                return []
            
            root = ET.fromstring(response.content)
            namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            
            urls = [elem.text for elem in root.findall('.//ns:loc', namespaces)]
            return urls
    except Exception as e:
        st.error(f"Error fetching sitemap: {e}")
        return []


async def fetch_url_details(url, client):
    """Fetch URL status code, meta title, and description asynchronously."""
    try:
        response = await client.get(url, timeout=10, follow_redirects=True)
        status_code = response.status_code
        html = HTMLParser(response.text)
        
        title = html.css_first("title").text(strip=True) if html.css_first("title") else "N/A"
        meta_desc = html.css_first("meta[name='description']") 
        description = meta_desc.attrs.get("content", "N/A") if meta_desc else "N/A"
        site_name = html.css_first("meta[property='og:site_name']")
        site_name = site_name.attrs.get("content", "N/A") if site_name else "N/A"
        
        return url, status_code, title, description, site_name
    except Exception as e:
        return url, "Failed", f"Error: {str(e)[:50]}...", "N/A", "N/A"


async def check_specific_url(check_url, urls):
    """Check if a specific URL exists in the sitemap."""
    return check_url in urls


async def process_urls_in_batches(urls, batch_size=100, max_concurrent=50):
    """Process URLs in batches with a limit on concurrent requests."""
    results = []
    total_urls = len(urls)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    eta_text = st.empty()
    start_time = time.time()
    
    # Process in batches to avoid memory issues
    for batch_start in range(0, total_urls, batch_size):
        batch_end = min(batch_start + batch_size, total_urls)
        batch = urls[batch_start:batch_end]
        
        async with httpx.AsyncClient(limits=httpx.Limits(max_connections=max_concurrent)) as client:
            tasks = [fetch_url_details(url, client) for url in batch]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
        
        # Update progress
        completed = batch_end
        progress = completed / total_urls
        progress_bar.progress(progress)
        
        # Calculate ETA
        elapsed_time = time.time() - start_time
        urls_per_second = completed / elapsed_time if elapsed_time > 0 else 0
        remaining_urls = total_urls - completed
        remaining_seconds = remaining_urls / urls_per_second if urls_per_second > 0 else 0
        
        eta_minutes, eta_seconds = divmod(int(remaining_seconds), 60)
        
        status_text.write(f"Processed {completed}/{total_urls} URLs")
        eta_text.write(f"⏳ Estimated Time Left: {eta_minutes}m {eta_seconds}s | ✅ Completed: {completed} | ❌ Pending: {remaining_urls} | Speed: {urls_per_second:.1f} URLs/sec")
    
    return results


def main():
    st.title("Fast Sitemap Status Checker")
    
    sitemap_url = st.text_input("Enter Sitemap URL:", "https://www.profoundproperties.com/sitemap.xml")
    check_url = st.text_input("Enter URL to check:", "https://www.profoundproperties.com/")
    
    col1, col2 = st.columns(2)
    with col1:
        batch_size = st.number_input("Batch Size", min_value=10, max_value=500, value=100)
    with col2:
        max_concurrent = st.number_input("Max Concurrent Requests", min_value=10, max_value=100, value=50)
    
    if st.button("Start Checking"):
        with st.spinner("Fetching Sitemap URLs..."):
            urls = asyncio.run(fetch_sitemap_urls(sitemap_url))
            
            if not urls:
                st.error("No URLs found in the sitemap.")
                return
            
            total_urls = len(urls)
            st.info(f"Found {total_urls} URLs in the sitemap.")
            
            # Check if the specific URL exists in the sitemap
            url_found = asyncio.run(check_specific_url(check_url, urls))
            if url_found:
                st.success(f"URL {check_url} found in the sitemap.")
            else:
                st.error(f"URL {check_url} not found in the sitemap.")
                if not st.checkbox("Continue checking all URLs anyway"):
                    return
        
        st.info("Starting URL status check... This will be much faster than sequential processing!")
        
        # Process URLs in batches asynchronously
        results = asyncio.run(process_urls_in_batches(urls, batch_size, max_concurrent))
        
        # Convert to DataFrame
        df = pd.DataFrame(results, columns=["URL", "Status Code", "Meta Title", "Meta Description", "Site Name"])
        
        # Display DataFrame
        st.dataframe(df)
        
        # Download button
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "Download CSV",
            csv,
            "sitemap_report.csv",
            "text/csv",
            key="download-csv"
        )

if __name__ == "__main__":
    main()
