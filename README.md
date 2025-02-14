# Sitemap SEO Report Streamlit App

## Overview
This Streamlit app fetches the sitemap of a given URL, extracts all URLs listed in the sitemap, and generates a minified SEO report. The report includes:
- HTTP status codes of the URLs
- Meta title
- Meta description
- Site name (if available)

It also provides a downloadable CSV file containing the report.

## Features
- Extracts URLs from the provided XML sitemap
- Fetches metadata (title, description, site name) for each URL
- Displays HTTP status codes for all URLs
- Provides estimated time left for completion
- Allows downloading the report as a CSV file

## Installation
Ensure you have Python installed, then install the required dependencies:

```sh
pip install streamlit httpx pandas selectolax lxml
```

## Usage
1. Run the Streamlit app:
   ```sh
   streamlit run app.py
   ```
2. Enter the sitemap URL in the input field (default example provided)
3. Click the **Start Checking** button to initiate the process
4. View results in a tabular format
5. Download the report as a CSV file

## Example Output
| URL                                | Status Code | Meta Title    | Meta Description    | Site Name         |
|------------------------------------|-------------|--------------|--------------------|------------------|
| https://example.com/page1         | 200         | Page 1 Title | Description 1      | Example Site     |
| https://example.com/page2         | 404         | N/A          | N/A                | N/A              |

## Notes
- The script checks the first 10 URLs from the sitemap to optimize performance.
- If the sitemap URL is invalid or inaccessible, an error message is displayed.
- The app follows redirects automatically when fetching pages.

## Author
Developed by ChintanDiwkar


