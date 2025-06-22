import os
import re
import time
import requests
import subprocess
from lxml import etree
from typing import List, Dict, Any, Optional
import logging
import tempfile
import shutil

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GrobidParser:
    """
    A class to process PDF documents using GROBID running in a Docker container.
    This version uses a temporary container for each processing operation,
    avoiding the need for a persistent daemon.
    """
    
    def __init__(self, grobid_image: str = "lfoppiano/grobid:0.8.0"):
        self.grobid_image = grobid_image
        self._ensure_image_available()

    def _ensure_image_available(self) -> None:
        """Ensure the GROBID Docker image is available locally."""
        try:
            # Check if image exists
            result = subprocess.run(
                ["docker", "images", "-q", self.grobid_image],
                capture_output=True,
                text=True
            )
            
            if not result.stdout.strip():
                logger.info(f"Pulling GROBID image: {self.grobid_image}")
                subprocess.run(
                    ["docker", "pull", self.grobid_image],
                    check=True,
                    capture_output=True
                )
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to ensure GROBID image availability: {e}")
            raise RuntimeError("Could not ensure GROBID image availability")

    def process_pdf(self, pdf_path: str, **kwargs) -> Optional[str]:
        """
        Process a PDF file using GROBID in a temporary container.

        Args:
            pdf_path: The file path to the PDF document.
            **kwargs: Additional parameters for GROBID processing.

        Returns:
            The TEI XML content as a string, or None if an error occurs.
        """
        if not os.path.exists(pdf_path):
            logger.error(f"PDF file not found at {pdf_path}")
            return None

        # Create a temporary directory for the container
        with tempfile.TemporaryDirectory() as temp_dir:
            # Copy PDF to temp directory
            temp_pdf = os.path.join(temp_dir, os.path.basename(pdf_path))
            shutil.copy2(pdf_path, temp_pdf)

            # Default parameters
            default_params = {
                'consolidateHeader': 'true',
                'consolidateCitations': 'true',
                'consolidateFunders': 'true',
                'includeRawAffiliations': 'false',
                'includeRawCitations': 'false',
                'segmentSentences': 'false',
                'generateIDs': 'true',
                'addCoordinates': 'true'
            }
            params = {**default_params, **kwargs}

            container_name = None
            try:
                # Start a temporary container
                container_name = f"grobid-temp-{os.getpid()}"
                subprocess.run([
                    "docker", "run", "-d",
                    "--name", container_name,
                    "-v", f"{temp_dir}:/data",
                    self.grobid_image
                ], check=True, capture_output=True)

                # Wait for service to be ready
                for _ in range(30):  # 30 attempts, 2 seconds each
                    try:
                        response = requests.get("http://localhost:8070/api/isalive", timeout=2)
                        if response.status_code == 200 and response.text.strip() == "true":
                            break
                    except requests.RequestException:
                        pass
                    time.sleep(2)
                else:
                    raise RuntimeError("GROBID service did not become available")

                # Process the PDF
                with open(temp_pdf, 'rb') as f:
                    files = {'input': f}
                    response = requests.post(
                        "http://localhost:8070/api/processFulltextDocument",
                        files=files,
                        data=params,
                        timeout=120
                    )

                if response.status_code == 200:
                    return response.text
                else:
                    logger.error(f"Error processing PDF. Status: {response.status_code}")
                    logger.error(f"Response: {response.text}")
                    return None

            except Exception as e:
                logger.error(f"Error processing PDF: {e}")
                return None

            finally:
                # Clean up the temporary container
                if container_name:
                    try:
                        subprocess.run(
                            ["docker", "rm", "-f", container_name],
                            capture_output=True
                        )
                    except Exception as e:
                        logger.warning(f"Error cleaning up container: {e}")

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

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_pdf = os.path.join(temp_dir, os.path.basename(pdf_path))
            shutil.copy2(pdf_path, temp_pdf)

            container_name = None
            try:
                container_name = f"grobid-temp-{os.getpid()}"
                subprocess.run([
                    "docker", "run", "-d",
                    "--name", container_name,
                    "-v", f"{temp_dir}:/data",
                    self.grobid_image
                ], check=True, capture_output=True)

                # Wait for service
                for _ in range(30):
                    try:
                        response = requests.get("http://localhost:8070/api/isalive", timeout=2)
                        if response.status_code == 200 and response.text.strip() == "true":
                            break
                    except requests.RequestException:
                        pass
                    time.sleep(2)
                else:
                    raise RuntimeError("GROBID service did not become available")

                with open(temp_pdf, 'rb') as f:
                    files = {'input': f}
                    response = requests.post(
                        "http://localhost:8070/api/processHeaderDocument",
                        files=files,
                        timeout=60
                    )

                if response.status_code == 200:
                    return response.text
                else:
                    logger.error(f"Error processing header. Status: {response.status_code}")
                    return None

            except Exception as e:
                logger.error(f"Error processing header: {e}")
                return None

            finally:
                if container_name:
                    try:
                        subprocess.run(
                            ["docker", "rm", "-f", container_name],
                            capture_output=True
                        )
                    except Exception as e:
                        logger.warning(f"Error cleaning up container: {e}")

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

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_pdf = os.path.join(temp_dir, os.path.basename(pdf_path))
            shutil.copy2(pdf_path, temp_pdf)

            container_name = None
            try:
                container_name = f"grobid-temp-{os.getpid()}"
                subprocess.run([
                    "docker", "run", "-d",
                    "--name", container_name,
                    "-v", f"{temp_dir}:/data",
                    self.grobid_image
                ], check=True, capture_output=True)

                # Wait for service
                for _ in range(30):
                    try:
                        response = requests.get("http://localhost:8070/api/isalive", timeout=2)
                        if response.status_code == 200 and response.text.strip() == "true":
                            break
                    except requests.RequestException:
                        pass
                    time.sleep(2)
                else:
                    raise RuntimeError("GROBID service did not become available")

                with open(temp_pdf, 'rb') as f:
                    files = {'input': f}
                    response = requests.post(
                        "http://localhost:8070/api/processReferences",
                        files=files,
                        timeout=60
                    )

                if response.status_code == 200:
                    return response.text
                else:
                    logger.error(f"Error processing references. Status: {response.status_code}")
                    return None

            except Exception as e:
                logger.error(f"Error processing references: {e}")
                return None

            finally:
                if container_name:
                    try:
                        subprocess.run(
                            ["docker", "rm", "-f", container_name],
                            capture_output=True
                        )
                    except Exception as e:
                        logger.warning(f"Error cleaning up container: {e}")

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
                    if ref.getparent() is not None:
                        if ref.tail:
                            if ref.getprevious() is not None:
                                ref.getprevious().tail = (ref.getprevious().tail or '') + (ref.text or '') + ref.tail
                            else:
                                ref.getparent().text = (ref.getparent().text or '') + (ref.text or '') + ref.tail
                        ref.getparent().remove(ref)

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


if __name__ == '__main__':
    # Example usage
    PDF_FILE = "/Users/aditya/Documents/Codes/Projects/Gen AI assited Keynotes/AutoDeck/0. Input Data/AlphaFold.pdf"
    
    if not os.path.exists(PDF_FILE):
        print(f"PDF file not found: {PDF_FILE}")
        print("Please update the PDF_FILE path to test the parser.")
        exit(1)
    
    parser = GrobidParser()
    xml_output = parser.process_pdf(PDF_FILE)
    
    if xml_output:
        structured_data = GrobidParser.parse_grobid_xml(xml_output)
        print("\n--- Structured Document Output ---")
        import json
        print(json.dumps(structured_data[:3], indent=2))  # Show first 3 chunks
        print(f"\nSuccessfully parsed document into {len(structured_data)} chunks.")
    else:
        print("Failed to process PDF")