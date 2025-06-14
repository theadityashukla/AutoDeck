import os
import re
import time
import requests
import subprocess
from lxml import etree
from typing import List, Dict, Any, Optional
import logging

# --- Configuration ---
GROBID_URL = "http://localhost:8070"
CONTAINER_NAME = "grobid-daemon"

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GrobidParser:
    """
    A class to interact with a GROBID daemon running in Docker
    and parse PDF documents to structured TEI XML.
    
    This version assumes GROBID is running as a daemon service,
    not managing the container lifecycle itself.
    """
    
    def __init__(self, grobid_url: str = GROBID_URL):
        self.grobid_url = grobid_url
        self.container_name = CONTAINER_NAME

    def is_service_available(self) -> bool:
        """
        Check if GROBID service is available and responding.
        
        Returns:
            True if service is available, False otherwise.
        """
        try:
            response = requests.get(f"{self.grobid_url}/api/isalive", timeout=5)
            return response.status_code == 200 and response.text.strip() == "true"
        except requests.RequestException:
            return False

    def wait_for_service(self, timeout: int = 60) -> bool:
        """
        Wait for GROBID service to become available.
        
        Args:
            timeout: Maximum time to wait in seconds.
            
        Returns:
            True if service becomes available, False on timeout.
        """
        logger.info("Checking GROBID service availability...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.is_service_available():
                logger.info("GROBID service is available")
                return True
            
            elapsed = int(time.time() - start_time)
            logger.info(f"GROBID not ready yet. Waiting... ({elapsed}s)")
            time.sleep(2)
        
        logger.error(f"GROBID service did not become available within {timeout}s")
        return False

    def start_daemon(self) -> bool:
        """
        Start the GROBID daemon using docker-compose.
        
        Returns:
            True if daemon started successfully, False otherwise.
        """
        try:
            # Check if already running
            if self.is_service_available():
                logger.info("GROBID daemon is already running")
                return True
            
            logger.info("Starting GROBID daemon...")
            
            # First, check if container already exists and try to start it
            check_result = subprocess.run([
                "docker", "ps", "-a", "--filter", f"name={self.container_name}", "--format", "{{.Names}}"
            ], capture_output=True, text=True)
            
            if check_result.returncode == 0 and self.container_name in check_result.stdout:
                logger.info(f"Found existing container {self.container_name}, attempting to start it...")
                start_result = subprocess.run([
                    "docker", "start", self.container_name
                ], capture_output=True, text=True)
                
                if start_result.returncode == 0:
                    return self.wait_for_service(timeout=120)  # Give more time for restart
                else:
                    logger.warning(f"Could not start existing container: {start_result.stderr}")
                    # Remove the problematic container
                    subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True)
            
            # Try to start using docker-compose first
            if os.path.exists("docker-compose.yml"):
                logger.info("Found docker-compose.yml, using docker-compose...")
                result = subprocess.run(
                    ["docker-compose", "up", "-d"],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode == 0:
                    return self.wait_for_service(timeout=120)
                else:
                    logger.warning(f"docker-compose failed: {result.stderr}")
            
            # Check available GROBID images
            logger.info("Checking available GROBID Docker images...")
            images_result = subprocess.run([
                "docker", "images", "--filter", "reference=*grobid*", "--format", "{{.Repository}}:{{.Tag}}"
            ], capture_output=True, text=True)
            
            available_images = []
            if images_result.returncode == 0:
                available_images = [img.strip() for img in images_result.stdout.split('\n') if img.strip()]
                logger.info(f"Available GROBID images: {available_images}")
            
            # Try different image names in order of preference
            image_candidates = [
                "grobid-custom:latest",
                # "lfoppiano/grobid:0.8.0",
                # "lfoppiano/grobid:latest",
                # "grobid/grobid:0.8.0",
                "grobid/grobid:latest"
            ]
            
            # Prioritize available images
            for img in available_images:
                if img not in image_candidates:
                    image_candidates.insert(0, img)
            
            for image in image_candidates:
                logger.info(f"Trying to start GROBID with image: {image}")
                
                # Remove any existing container first
                subprocess.run(["docker", "rm", "-f", self.container_name], 
                             capture_output=True, text=True)
                
                result = subprocess.run([
                    "docker", "run", "-d",
                    "--name", self.container_name,
                    "--restart", "unless-stopped",
                    "-p", "8070:8070",
                    image
                ], capture_output=True, text=True)
                
                if result.returncode == 0:
                    logger.info(f"Successfully started container with image {image}")
                    # Give GROBID more time to start up (it can be slow)
                    if self.wait_for_service(timeout=180):
                        return True
                    else:
                        logger.warning(f"Container started but service not available for {image}")
                        # Check container logs for debugging
                        logs_result = subprocess.run([
                            "docker", "logs", "--tail", "20", self.container_name
                        ], capture_output=True, text=True)
                        if logs_result.returncode == 0:
                            logger.info(f"Container logs:\n{logs_result.stdout}")
                        continue
                else:
                    logger.warning(f"Failed to start with image {image}: {result.stderr}")
                    continue
            
            # If we get here, all images failed
            logger.error("Failed to start GROBID with any available image")
            
            # Try pulling the official image as last resort
            logger.info("Attempting to pull official GROBID image...")
            pull_result = subprocess.run([
                "docker", "pull", "lfoppiano/grobid:0.8.0"
            ], capture_output=True, text=True, timeout=600)
            
            if pull_result.returncode == 0:
                logger.info("Successfully pulled lfoppiano/grobid:0.8.0, attempting to start...")
                subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True)
                
                result = subprocess.run([
                    "docker", "run", "-d",
                    "--name", self.container_name,
                    "--restart", "unless-stopped",
                    "-p", "8070:8070",
                    "lfoppiano/grobid:0.8.0"
                ], capture_output=True, text=True)
                
                if result.returncode == 0:
                    return self.wait_for_service(timeout=180)
            
            return False
                
        except Exception as e:
            logger.error(f"Error starting GROBID daemon: {e}")
            return False

    def stop_daemon(self) -> bool:
        """
        Stop the GROBID daemon.
        
        Returns:
            True if daemon stopped successfully, False otherwise.
        """
        try:
            logger.info("Stopping GROBID daemon...")
            
            # Try docker-compose first
            if os.path.exists("docker-compose.yml"):
                result = subprocess.run(
                    ["docker-compose", "down"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    logger.info("GROBID daemon stopped via docker-compose")
                    return True
            
            # Fallback to direct docker stop
            result = subprocess.run([
                "docker", "stop", self.container_name
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                subprocess.run(["docker", "rm", self.container_name], capture_output=True)
                logger.info("GROBID daemon stopped")
                return True
            else:
                logger.warning(f"Could not stop daemon: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error stopping GROBID daemon: {e}")
            return False

    def process_pdf(self, pdf_path: str, **kwargs) -> Optional[str]:
        """
        Process a PDF file using the GROBID service.

        Args:
            pdf_path: The file path to the PDF document.
            **kwargs: Additional parameters for GROBID processing.

        Returns:
            The TEI XML content as a string, or None if an error occurs.
        """
        if not os.path.exists(pdf_path):
            logger.error(f"PDF file not found at {pdf_path}")
            return None

        if not self.is_service_available():
            logger.error("GROBID service is not available")
            return None

        logger.info(f"Processing PDF: {pdf_path}")
        
        # Default parameters - can be overridden via kwargs
        default_params = {
            'consolidateHeader': 'true',
            'consolidateCitations': 'true',
            'consolidateFunders': 'true',
            'includeRawAffiliations': 'false',
            'includeRawCitations': 'false',
            'segmentSentences': 'false',
            'generateIDs': 'true',  # Essential for linking
            'addCoordinates': 'true'  # Essential for extractor
        }
        
        # Update with any provided kwargs
        params = {**default_params, **kwargs}
        
        try:
            with open(pdf_path, 'rb') as f:
                files = {'input': f}
                
                response = requests.post(
                    f"{self.grobid_url}/api/processFulltextDocument",
                    files=files,
                    data=params,
                    timeout=120
                )
                
                if response.status_code == 200:
                    logger.info("Successfully processed PDF")
                    return response.text
                else:
                    logger.error(f"Error processing PDF. Status: {response.status_code}")
                    logger.error(f"Response: {response.text}")
                    return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error while processing PDF: {e}")
            return None

    def process_header(self, pdf_path: str) -> Optional[str]:
        """
        Process only the header/metadata of a PDF using GROBID.
        
        Args:
            pdf_path: Path to the PDF file.
            
        Returns:
            TEI XML string containing header information, or None if error.
        """
        if not os.path.exists(pdf_path):
            logger.error(f"PDF file not found at {pdf_path}")
            return None

        if not self.is_service_available():
            logger.error("GROBID service is not available")
            return None

        try:
            with open(pdf_path, 'rb') as f:
                files = {'input': f}
                response = requests.post(
                    f"{self.grobid_url}/api/processHeaderDocument",
                    files=files,
                    timeout=60
                )
                
                if response.status_code == 200:
                    return response.text
                else:
                    logger.error(f"Error processing header. Status: {response.status_code}")
                    return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error while processing header: {e}")
            return None

    def process_references(self, pdf_path: str) -> Optional[str]:
        """
        Process only the references section of a PDF using GROBID.
        
        Args:
            pdf_path: Path to the PDF file.
            
        Returns:
            TEI XML string containing references, or None if error.
        """
        if not os.path.exists(pdf_path):
            logger.error(f"PDF file not found at {pdf_path}")
            return None

        if not self.is_service_available():
            logger.error("GROBID service is not available")
            return None

        try:
            with open(pdf_path, 'rb') as f:
                files = {'input': f}
                response = requests.post(
                    f"{self.grobid_url}/api/processReferences",
                    files=files,
                    timeout=60
                )
                
                if response.status_code == 200:
                    return response.text
                else:
                    logger.error(f"Error processing references. Status: {response.status_code}")
                    return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error while processing references: {e}")
            return None

    @staticmethod
    def parse_grobid_xml(xml_string: str) -> List[Dict[str, Any]]:
        """
        Parse GROBID TEI XML and extract structured content blocks,
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
                # Remove references to clean up text
                for ref in elem.xpath('.//tei:ref', namespaces=ns):
                    # Modified line: Use getparent().remove(ref) instead of drop_tree()
                    if ref.getparent() is not None:
                        # Append tail to previous sibling or parent text before removal
                        if ref.tail:
                            if ref.getprevious() is not None:
                                ref.getprevious().tail = (ref.getprevious().tail or '') + (ref.text or '') + ref.tail
                            else:
                                ref.getparent().text = (ref.getparent().text or '') + (ref.text or '') + ref.tail
                        ref.getparent().remove(ref) # Corrected line
                    

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

            # Process main body content
            body = root.xpath('//tei:body/tei:div', namespaces=ns)
            for div in body:
                traverse_divs(div)

            return content_blocks

        except etree.XMLSyntaxError as e:
            logger.error(f"Error parsing XML: {e}")
            return []


# Context manager for automatic daemon management
class GrobidDaemon:
    """
    Context manager for GROBID daemon that automatically starts and stops the service.
    """
    
    def __init__(self, auto_start: bool = True, auto_stop: bool = False):
        self.parser = GrobidParser()
        self.auto_start = auto_start
        self.auto_stop = auto_stop
        self.started_here = False

    def __enter__(self):
        if self.auto_start and not self.parser.is_service_available():
            logger.info("Starting GROBID daemon...")
            if self.parser.start_daemon():
                self.started_here = True
            else:
                raise RuntimeError("Failed to start GROBID daemon")
        return self.parser

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.auto_stop and self.started_here:
            logger.info("Stopping GROBID daemon...")
            self.parser.stop_daemon()


if __name__ == '__main__':
    # Example usage with automatic daemon management
    PDF_FILE = "/Users/aditya/Documents/Codes/Projects/Gen AI assited Keynotes/AutoDeck/0. Input Data/AlphaFold.pdf"
    
    if not os.path.exists(PDF_FILE):
        print(f"PDF file not found: {PDF_FILE}")
        print("Please update the PDF_FILE path to test the parser.")
        exit(1)
    
    # First, let's check Docker status
    print("=== Docker Diagnostics ===")
    try:
        docker_version = subprocess.run(["docker", "--version"], capture_output=True, text=True)
        if docker_version.returncode == 0:
            print(f"Docker version: {docker_version.stdout.strip()}")
        else:
            print("Docker not found or not running!")
            exit(1)
            
        # Check if Docker daemon is running
        docker_info = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if docker_info.returncode != 0:
            print("Docker daemon is not running!")
            print("Please start Docker Desktop or Docker daemon")
            exit(1)
        
        # Check existing GROBID containers
        existing_containers = subprocess.run([
            "docker", "ps", "-a", "--filter", "name=grobid", "--format", "{{.Names}} {{.Status}} {{.Image}}"
        ], capture_output=True, text=True)
        
        if existing_containers.returncode == 0 and existing_containers.stdout.strip():
            print("Existing GROBID containers:")
            print(existing_containers.stdout.strip())
        
        # Check available GROBID images
        grobid_images = subprocess.run([
            "docker", "images", "--filter", "reference=*grobid*", "--format", "{{.Repository}}:{{.Tag}} ({{.Size}})"
        ], capture_output=True, text=True)
        
        if grobid_images.returncode == 0 and grobid_images.stdout.strip():
            print("Available GROBID images:")
            print(grobid_images.stdout.strip())
        else:
            print("No GROBID images found locally")
            
    except Exception as e:
        print(f"Error checking Docker: {e}")
        exit(1)
    
    print("\n=== Starting GROBID Processing ===")
    
    with GrobidDaemon(auto_start=True, auto_stop=False) as parser:
        xml_output = parser.process_pdf(PDF_FILE)
        
        if xml_output:
            structured_data = GrobidParser.parse_grobid_xml(xml_output)
            print("\n--- Structured Document Output ---")
            import json
            print(json.dumps(structured_data[:3], indent=2))  # Show first 3 chunks
            print(f"\nSuccessfully parsed document into {len(structured_data)} chunks.")
        else:
            print("Failed to process PDF")