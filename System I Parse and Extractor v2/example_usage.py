#!/usr/bin/env python3
"""
Example usage of SuperGrobid parser
Demonstrates how to use the parser programmatically
"""

import json
from pathlib import Path
from supergrobid import SuperGrobidParser


def example_single_file_parsing():
    """Example: Parse a single PDF file."""
    print("=== Single File Parsing Example ===")
    
    # Initialize parser
    parser = SuperGrobidParser("config.yaml")
    
    # Example PDF path (replace with actual path)
    pdf_path = "../0. Input Data/AlphaFold.pdf"
    
    if not Path(pdf_path).exists():
        print(f"⚠️  PDF file not found: {pdf_path}")
        print("Please update the pdf_path variable with a valid PDF file.")
        return
    
    # Parse the document
    result = parser.parse(
        pdf_path=pdf_path,
        output_format="markdown",
        output_path="output/example_output.md"
    )
    
    if result["success"]:
        print(f"✅ Successfully parsed {pdf_path}")
        print(f"⏱️  Parsing time: {result['parsing_time']:.2f} seconds")
        
        # Display statistics
        stats = result["statistics"]
        print(f"📊 Statistics:")
        print(f"  • PyMuPDF blocks: {stats['pymupdf_blocks']}")
        print(f"  • Nougat elements: {stats['nougat_elements']}")
        print(f"  • Reconciled elements: {stats['reconciled_elements']}")
        print(f"  • Tables: {stats['tables']}")
        print(f"  • Equations: {stats['equations']}")
        print(f"  • References: {stats['references']}")
        
        # Display sample output
        output_text = result["output"]
        print(f"\n📄 Sample output (first 500 characters):")
        print("-" * 50)
        print(output_text[:500] + "..." if len(output_text) > 500 else output_text)
        print("-" * 50)
        
    else:
        print(f"❌ Failed to parse: {result.get('error', 'Unknown error')}")


def example_batch_parsing():
    """Example: Parse multiple PDF files in batch."""
    print("\n=== Batch Parsing Example ===")
    
    # Initialize parser
    parser = SuperGrobidParser("config.yaml")
    
    # Example directory with PDFs (replace with actual path)
    input_dir = "../0. Input Data"
    
    if not Path(input_dir).exists():
        print(f"⚠️  Input directory not found: {input_dir}")
        print("Please update the input_dir variable with a valid directory.")
        return
    
    # Find PDF files
    pdf_files = list(Path(input_dir).glob("*.pdf"))
    
    if not pdf_files:
        print(f"⚠️  No PDF files found in {input_dir}")
        return
    
    print(f"📁 Found {len(pdf_files)} PDF files to process")
    
    # Parse batch
    results = parser.parse_batch(
        pdf_paths=[str(f) for f in pdf_files],
        output_format="json",
        output_dir="output/batch"
    )
    
    # Display results
    successful = sum(1 for r in results if r["success"])
    failed = len(results) - successful
    total_time = sum(r.get("parsing_time", 0) for r in results)
    
    print(f"\n📊 Batch processing completed:")
    print(f"  ✅ Successful: {successful}")
    print(f"  ❌ Failed: {failed}")
    print(f"  ⏱️  Total time: {total_time:.2f} seconds")
    
    # Display details for failed files
    if failed > 0:
        print("\n❌ Failed files:")
        for result in results:
            if not result["success"]:
                print(f"  • {result['input_file']}: {result.get('error', 'Unknown error')}")


def example_different_formats():
    """Example: Generate output in different formats."""
    print("\n=== Multiple Output Formats Example ===")
    
    # Initialize parser
    parser = SuperGrobidParser("config.yaml")
    
    # Example PDF path
    pdf_path = "../0. Input Data/AlphaFold.pdf"
    
    if not Path(pdf_path).exists():
        print(f"⚠️  PDF file not found: {pdf_path}")
        return
    
    # Generate different output formats
    formats = ["markdown", "json", "xml"]
    
    for output_format in formats:
        print(f"\n🔄 Generating {output_format.upper()} output...")
        
        result = parser.parse(
            pdf_path=pdf_path,
            output_format=output_format,
            output_path=f"output/example.{output_format}"
        )
        
        if result["success"]:
            print(f"✅ {output_format.upper()} output generated successfully")
            print(f"   File: output/example.{output_format}")
            print(f"   Size: {len(result['output'])} characters")
        else:
            print(f"❌ Failed to generate {output_format.upper()} output")


def example_component_usage():
    """Example: Use individual components directly."""
    print("\n=== Component Usage Example ===")
    
    # Initialize parser
    parser = SuperGrobidParser("config.yaml")
    
    # Example PDF path
    pdf_path = "../0. Input Data/AlphaFold.pdf"
    
    if not Path(pdf_path).exists():
        print(f"⚠️  PDF file not found: {pdf_path}")
        return
    
    # Use PyMuPDF extractor directly
    print("🔍 Using PyMuPDF extractor...")
    pymupdf_output = parser.pymupdf_extractor.extract(pdf_path)
    print(f"   Extracted {len(pymupdf_output)} text blocks")
    
    # Use LayoutParser extractor directly
    print("🔍 Using LayoutParser extractor...")
    layout_output = parser.layout_extractor.extract(pdf_path)
    print(f"   Detected {len(layout_output)} layout regions")
    
    # Group regions by type
    regions_by_type = {}
    for region in layout_output:
        region_type = region["type"]
        if region_type not in regions_by_type:
            regions_by_type[region_type] = []
        regions_by_type[region_type].append(region)
    
    print("   Regions by type:")
    for region_type, regions in regions_by_type.items():
        print(f"     • {region_type}: {len(regions)} regions")


def example_configuration():
    """Example: Working with configuration."""
    print("\n=== Configuration Example ===")
    
    # Initialize parser
    parser = SuperGrobidParser("config.yaml")
    
    # Get current configuration
    config = parser.get_config()
    print("📋 Current configuration:")
    print(f"  • Similarity method: {config['reconciliation']['similarity']['method']}")
    print(f"  • Similarity threshold: {config['reconciliation']['similarity']['threshold']}")
    print(f"  • Output formats: {config['output']['formats']}")
    
    # Update configuration
    print("\n⚙️  Updating configuration...")
    new_config = {
        "reconciliation": {
            "similarity": {
                "method": "cosine",
                "threshold": 0.9
            }
        }
    }
    parser.update_config(new_config)
    
    # Verify update
    updated_config = parser.get_config()
    print(f"  ✅ Updated similarity method: {updated_config['reconciliation']['similarity']['method']}")
    print(f"  ✅ Updated similarity threshold: {updated_config['reconciliation']['similarity']['threshold']}")


def example_system_info():
    """Example: Get system information."""
    print("\n=== System Information Example ===")
    
    # Initialize parser
    parser = SuperGrobidParser("config.yaml")
    
    # Get system statistics
    stats = parser.get_statistics()
    
    print("🔧 System Information:")
    print(f"  • Version: {stats['version']}")
    print(f"  • Supported formats: {', '.join(stats['supported_formats'])}")
    
    print("\n📦 Component Status:")
    for component, status in stats['components'].items():
        status_icon = "✅" if "Available" in status else "❌"
        print(f"  {status_icon} {component}: {status}")
    
    print("\n⚙️  Configuration:")
    config_info = stats['configuration']
    print(f"  • Similarity method: {config_info['similarity_method']}")
    print(f"  • Similarity threshold: {config_info['similarity_threshold']}")


def main():
    """Run all examples."""
    print("🚀 SuperGrobid Example Usage")
    print("=" * 50)
    
    # Create output directory
    Path("output").mkdir(exist_ok=True)
    Path("output/batch").mkdir(exist_ok=True)
    
    try:
        # Run examples
        example_single_file_parsing()
        example_batch_parsing()
        example_different_formats()
        example_component_usage()
        example_configuration()
        example_system_info()
        
        print("\n✅ All examples completed successfully!")
        print("📁 Check the 'output' directory for generated files.")
        
    except Exception as e:
        print(f"\n❌ Error running examples: {e}")
        print("Make sure all dependencies are installed and PDF files are available.")


if __name__ == "__main__":
    main() 