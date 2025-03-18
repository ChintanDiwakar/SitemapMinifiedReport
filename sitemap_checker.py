import streamlit as st
import httpx
import pandas as pd
from selectolax.parser import HTMLParser
import xml.etree.ElementTree as ET
import asyncio
import time

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

def run_async_task(async_func, *args):
    """Run an async function inside Streamlit's event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(async_func(*args))

def main():
    st.title("Fast Sitemap Status Checker")
    
    sitemap_url = st.text_input("Enter Sitemap URL:", "https://www.profoundproperties.com/sitemap.xml")
    check_url = st.text_input("Enter URL to check:", "https://www.profoundproperties.com/")
    
    col1, col2 = st.columns(2)
    with col1:
        batch_size = st.number_input("Batch Size", min_value=10, max_value=500, value=100)
    with col2:
        max_concurrent = st.number_input("Max Concurrent Requests", min_value=10, max_value=100, value=50)

    if "continue_checking" not in st.session_state:
        st.session_state.continue_checking = False  # Default state for checkbox

    if st.button("Start Checking"):
        with st.spinner("Fetching Sitemap URLs..."):
            urls = run_async_task(fetch_sitemap_urls, sitemap_url)
            
            if not urls:
                st.error("No URLs found in the sitemap.")
                return
            
            total_urls = len(urls)
            st.info(f"Found {total_urls} URLs (excluding locales) in the sitemap.")
            
            url_found = check_url in urls
            if url_found:
                st.success(f"✅ URL {check_url} **exists** in the sitemap.")
            else:
                st.error(f"❌ URL {check_url} **not found** in the sitemap.")
                
                # Checkbox to allow users to continue processing all URLs
                st.session_state.continue_checking = st.checkbox("Continue checking all URLs anyway")

                # If checkbox is not selected, stop execution
                if not st.session_state.continue_checking:
                    st.warning("Checking stopped. Please check your sitemap URL or enable the checkbox to continue.")
                    return

        st.info("🚀 Starting URL status check...")
        
        results = run_async_task(process_urls_in_batches, urls, batch_size, max_concurrent)
        
        df = pd.DataFrame(results, columns=["URL", "Status Code", "Meta Title", "Meta Description", "Site Name"])
        
        status_filter = st.multiselect("Filter by Status Code:", df["Status Code"].unique(), default=[200, 404])
        filtered_df = df[df["Status Code"].isin(status_filter)]
        st.dataframe(filtered_df)
        
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button("Download CSV", csv, "sitemap_report.csv", "text/csv", key="download-csv")

if __name__ == "__main__":
    main()
