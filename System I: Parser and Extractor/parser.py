import os
import re
import time
import requests
import subprocess
from lxml import etree
from typing import List, Dict, Any, Optional

# --- Configuration ---
GROBID_IMAGE = "grobid/grobid:0.8.2"
GROBID_PORT = "8070"
GROBID_URL = f"http://localhost:{GROBID_PORT}"
# For M1/M2/M3 Macs, Docker will automatically use the correct ARM64 architecture for this image.
# The --platform linux/amd64 flag can be added if you need to force the x86 version.
DOCKER_COMMAND = [
    "docker", "run", "--rm", "--init",
    "-p", f"{GROBID_PORT}:{GROBID_PORT}",
    GROBID_IMAGE
]

class GrobidParser:
    """
    A class to manage the GROBID service in a Docker container
    and parse PDF documents to structured TEI XML.
    """
    def __init__(self):
        self.grobid_container: Optional[subprocess.Popen] = None
        self.container_name = "grobid-parser-container"

    def start_grobid(self) -> bool:
        """
        Starts the GROBID Docker container.
        Returns True if successful, False otherwise.
        """
        print("Starting GROBID container...")
        try:
            # Clean up any old container with the same name to avoid conflicts
            subprocess.run(["docker", "rm", "-f", self.container_name], check=False, capture_output=True)
            
            cmd = [
                "docker", "run", "--rm", "--init", "--name", self.container_name,
                "-p", f"{GROBID_PORT}:{GROBID_PORT}", GROBID_IMAGE
            ]
            self.grobid_container = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            print(f"GROBID container '{self.container_name}' started with PID: {self.grobid_container.pid}")
            
            return self._wait_for_service()
        except FileNotFoundError:
            print("Error: 'docker' command not found. Is Docker installed and in your PATH?")
            return False
        except Exception as e:
            print(f"An unexpected error occurred while starting GROBID: {e}")
            if self.grobid_container:
                # If something went wrong, print the logs we have
                stdout, stderr = self.grobid_container.communicate()
                print("\n--- Docker Logs on Failure ---")
                print("STDOUT:\n" + stdout)
                print("STDERR:\n" + stderr)
                print("----------------------------")
            return False

    def _wait_for_service(self, timeout: int = 120) -> bool:
        """
        Waits for the GROBID service to become available.
        """
        print("Waiting for GROBID service to be ready...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{GROBID_URL}/api/isalive")
                if response.status_code == 200 and response.text == "true":
                    print("GROBID service is alive.")
                    return True
            except requests.ConnectionError:
                # This is expected while the service is starting up.
                # Adding a print statement here to show progress.
                print(f"  - GROBID not ready yet. Waiting... ({int(time.time() - start_time)}s)")
                time.sleep(2)
        
        # --- ENHANCED DEBUGGING ON TIMEOUT ---
        print("\nError: GROBID service did not start within the timeout period.")
        print("--- Capturing Docker container logs for debugging ---")
        self.grobid_container.terminate() # Ensure the process is stopped
        stdout, stderr = self.grobid_container.communicate()
        print("STDOUT from container:")
        print(stdout)
        print("\nSTDERR from container:")
        print(stderr)
        print("--- End of logs ---")
        # --- END OF DEBUGGING ---
        
        # Attempt to clean up the named container after failure
        self.stop_grobid()
        return False

    def stop_grobid(self):
        """
        Stops the GROBID Docker container gracefully.
        """
        print(f"Attempting to stop and remove GROBID container '{self.container_name}'...")
        try:
            # Use the container name to stop it. It's more reliable.
            subprocess.run(
                ["docker", "stop", self.container_name],
                check=True, capture_output=True, timeout=20
            )
            print("GROBID container stopped successfully.")
        except FileNotFoundError:
            print("Warning: 'docker' command not found. Cannot stop container.")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            # This can happen if the container already crashed or was manually stopped.
            error_output = e.stderr.decode('utf-8', errors='ignore') if hasattr(e, 'stderr') else str(e)
            print(f"Could not stop container '{self.container_name}' (it may have already stopped): {error_output.strip()}")
        finally:
             self.grobid_container = None


    def process_pdf(self, pdf_path: str) -> Optional[str]:
        """
        Processes a PDF file using the GROBID service.

        Args:
            pdf_path: The file path to the PDF document.

        Returns:
            The TEI XML content as a string, or None if an error occurs.
        """
        if not os.path.exists(pdf_path):
            print(f"Error: PDF file not found at {pdf_path}")
            return None

        print(f"Processing PDF: {pdf_path}")
        try:
            with open(pdf_path, 'rb') as f:
                params = {
                    'consolidateHeader': 'true',
                    'consolidateCitations': 'true',
                    'consolidateFunders': 'true',
                    'includeRawAffiliations': 'false',
                    'includeRawCitations': 'false',
                    'segmentSentences': 'false',
                    'generateIDs': 'true', # Essential for linking
                    'addCoordinates': 'true' # Essential for extractor
                }
                files = {'input': f}
                
                response = requests.post(
                    f"{GROBID_URL}/api/processFulltextDocument",
                    files=files,
                    data=params,
                    timeout=120
                )
                
                if response.status_code == 200:
                    print("Successfully processed PDF.")
                    return response.text
                else:
                    print(f"Error processing PDF. Status: {response.status_code}, Body: {response.text}")
                    return None

        except requests.exceptions.RequestException as e:
            print(f"An error occurred during the request to GROBID: {e}")
            return None

    @staticmethod
    def parse_grobid_xml(xml_string: str) -> List[Dict[str, Any]]:
        """
        Parses GROBID TEI XML and extracts structured content blocks,
        including paragraphs, figures, and tables with coordinates.

        Args:
            xml_string: The TEI XML content from GROBID.

        Returns:
            A list of dictionaries, where each dictionary is a content chunk.
        """
        if not xml_string:
            return []
            
        try:
            parser = etree.XMLParser(recover=True)
            root = etree.fromstring(xml_string.encode("utf-8"), parser=parser)
            ns = {'tei': 'http://www.tei-c.org/ns/1.0'}
            content_blocks = []

            # Extract abstract first, as it's outside the main body divs
            abstract_p = root.xpath('//tei:profileDesc/tei:abstract/tei:div/tei:p', namespaces=ns)
            if abstract_p:
                 text = ''.join(abstract_p[0].itertext()).strip()
                 text = re.sub(r'\s+', ' ', text)
                 content_blocks.append({
                     "type": "paragraph",
                     "text": text,
                     "headers": ["Abstract"],
                     "coords": abstract_p[0].get("coords")
                 })


            def process_element(elem, headers):
                """Helper to process a single element (p, figure, etc.)"""
                for ref in elem.xpath('.//tei:ref', namespaces=ns):
                    if ref.tail:
                        if ref.getprevious() is not None:
                             ref.getprevious().tail = (ref.getprevious().tail or '') + (ref.text or '') + ref.tail
                        else:
                             ref.getparent().text = (ref.getparent().text or '') + (ref.text or '') + ref.tail
                    ref.drop_tree()

                if etree.QName(elem).localname == 'p':
                    text = ''.join(elem.itertext()).strip()
                    text = re.sub(r'\s+', ' ', text)
                    if text:
                        return {
                            "type": "paragraph",
                            "text": text,
                            "headers": headers,
                            "coords": elem.get("coords")
                        }
                
                elif etree.QName(elem).localname == 'figure':
                    is_table = len(elem.xpath('.//tei:table', namespaces=ns)) > 0
                    fig_type = "table" if is_table else "figure"
                    
                    head_text = ''.join(elem.xpath('./tei:head', namespaces=ns)[0].itertext()).strip() if elem.xpath('./tei:head', namespaces=ns) else ""
                    desc_text = ''.join(elem.xpath('./tei:figDesc', namespaces=ns)[0].itertext()).strip() if elem.xpath('./tei:figDesc', namespaces=ns) else ""
                    
                    return {
                        "type": fig_type,
                        "id": elem.get('{http://www.w3.org/XML/1998/namespace}id'),
                        "header_text": re.sub(r'\s+', ' ', head_text),
                        "description": re.sub(r'\s+', ' ', desc_text),
                        "coords": elem.get("coords"),
                        "headers": headers,
                    }
                return None


            def traverse_divs(div, parent_headers=[]):
                """Recursively traverse <div> elements and process their children."""
                head = div.xpath('./tei:head', namespaces=ns)
                current_headers = parent_headers + [''.join(head[0].itertext()).strip()] if head else parent_headers
                
                for child in div.xpath('./tei:p | ./tei:figure', namespaces=ns):
                    block = process_element(child, current_headers)
                    if block:
                        content_blocks.append(block)

                for child_div in div.xpath('./tei:div', namespaces=ns):
                    traverse_divs(child_div, current_headers)

            body = root.xpath('//tei:body/tei:div', namespaces=ns)
            for div in body:
                traverse_divs(div)

            return content_blocks

        except etree.XMLSyntaxError as e:
            print(f"Error parsing XML: {e}")
            return []


if __name__ == '__main__':
    PDF_FILE = "/Users/aditya/Documents/Codes/Projects/Gen AI assited Keynotes/AutoDeck/0. Input Data/AlphaFold.pdf"
    if not os.path.exists(PDF_FILE):
        print(f"Creating a dummy PDF named '{PDF_FILE}' for demonstration.")
        try:
            from fpdf import FPDF
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.cell(200, 10, text="This is a sample PDF for the GROBID parser.", ln=True, align='C')
            pdf.output(PDF_FILE)
        except ImportError:
            print("\nWARNING: fpdf library not found. Cannot create a sample PDF.")
            print("Please create a file named 'sample.pdf' manually to run the demo.")
            print("You can install it with: pip install fpdf\n")
            exit()


    parser = GrobidParser()
    # Using a with statement is not feasible here as start/stop are not __enter__/__exit__
    # So we use a try/finally block to ensure cleanup.
    if parser.start_grobid():
        try:
            xml_output = parser.process_pdf(PDF_FILE)
            
            if xml_output:
                structured_data = GrobidParser.parse_grobid_xml(xml_output)
                print("\n--- Structured Document Output ---")
                import json
                print(json.dumps(structured_data, indent=2))
                print(f"\nSuccessfully parsed document into {len(structured_data)} chunks.")

        finally:
            parser.stop_grobid()

