import streamlit as st
import httpx
import pandas as pd
from selectolax.parser import HTMLParser
from lxml import etree
from io import BytesIO
import time

import xml.etree.ElementTree as ET


def fetch_sitemap_urls(sitemap_url):
    """Fetch and parse XML sitemap to extract all URLs."""
    try:
        response = httpx.get(sitemap_url, timeout=10, follow_redirects=True)
        if response.status_code != 200:
            st.error(f"Failed to fetch sitemap. Status Code: {response.status_code}")
            return []
        
        root = ET.fromstring(response.content)
        namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        urls = [elem.text for elem in root.findall('.//ns:loc', namespaces)]
        # Check first 100 URLs only
        # return urls[:10]
        return urls
    except Exception as e:
        st.error(f"Error fetching sitemap: {e}")
        return []
import json
def fetch_url_details(url):
    """Fetch URL status code, meta title, and description in headless mode."""
    try:
        response = httpx.get(url, timeout=10, follow_redirects=True)
        status_code = response.status_code
        html = HTMLParser(response.text)
        
        title = html.css_first("title").text(strip=True) if html.css_first("title") else "N/A"
        meta_desc = html.css_first("meta[name='description']") 
        description = meta_desc.attrs.get("content", "N/A") if meta_desc else "N/A"
        site_name = html.css_first("meta[property='og:site_name']")
        site_name = site_name.attrs.get("content", "N/A") if site_name else "N/A"







        




        
        return url, status_code, title, description, site_name
    except Exception:
        return url, "Failed", "N/A", "N/A"

def main():
    st.title("Sitemap Status Checker")

    
    sitemap_url = st.text_input("Enter Sitemap URL:", "https://www.profoundproperties.com/sitemap.xml")
    check_url = st.text_input("Enter URL to check:", "https://www.profoundproperties.com/")
    url_found = False
    
    if st.button("Start Checking"):
        st.write("Fetching Sitemap URLs... Please wait.")
        urls = fetch_sitemap_urls(sitemap_url)

        for i in urls:
            if i == check_url:
                st.write(f"URL {check_url} found in the sitemap.")
                url_found = True
                break
        if not url_found:
            st.error(f"URL {check_url} not found in the sitemap.")
            return
        
        if not urls:
            st.error("No URLs found in the sitemap.")
            return
        
        total_urls = len(urls)
        st.write(f"Found {total_urls} URLs. Checking Status...")

        results = []
        progress_bar = st.progress(0)
        
        status_text = st.empty()  # Placeholder for status update
        eta_text = st.empty()      # Placeholder for ETA
        
        start_time = time.time()

        for idx, url in enumerate(urls):
            # Calculate elapsed time and ETA
            elapsed_time = time.time() - start_time
            avg_time_per_url = elapsed_time / (idx + 1) if idx > 0 else 0
            remaining_time = avg_time_per_url * (total_urls - idx - 1)

            # Convert remaining time to minutes/seconds
            eta_minutes, eta_seconds = divmod(int(remaining_time), 60)

            # Update progress and status
            results.append(fetch_url_details(url))
            
            status_text.write(f"Checking URL {idx + 1}/{total_urls}: {url}")
            eta_text.write(f"⏳ Estimated Time Left: {eta_minutes}m {eta_seconds}s | ✅ Completed: {idx + 1} | ❌ Pending: {total_urls - idx - 1}")
            
            progress_bar.progress((idx + 1) / total_urls)

        # Convert to DataFrame
        df = pd.DataFrame(results, columns=["URL", "Status Code", "Meta Title", "Meta Description","Site Name"])
        
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
