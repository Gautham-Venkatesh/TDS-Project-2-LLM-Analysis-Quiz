from langchain_core.tools import tool
import requests
import os

@tool
def download_file(url: str, filename: str) -> str:
    """
    Download a file from a URL and save it with the given filename
    in the current working directory.

    Args:
        url (str): Direct URL to the file.
        filename (str): The filename to save the downloaded content as.

    Returns:
        str: Full path to the saved file or error message.
    """
    try:
        print(f"Downloading file from: {url}")

        # Make request with timeout
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        # Create directory
        directory_name = "LLMFiles"
        os.makedirs(directory_name, exist_ok=True)

        # Save file
        path = os.path.join(directory_name, filename)
        with open(path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        file_size = os.path.getsize(path)
        print(f"Downloaded {filename} successfully ({file_size} bytes)")

        return filename

    except requests.exceptions.Timeout:
        return f"Error: Download timeout for {url}"
    except requests.exceptions.RequestException as e:
        return f"Error downloading file: {type(e).__name__} - {str(e)}"
    except Exception as e:
        return f"Error saving file: {type(e).__name__} - {str(e)}"
