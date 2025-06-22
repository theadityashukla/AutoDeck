#!/usr/bin/env python3
"""
Command-line interface for SuperGrobid
"""

import click
import json
from pathlib import Path
from typing import List
import sys

from supergrobid import SuperGrobidParser


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """SuperGrobid - A Hybrid, Python-Native Scientific Document Parser"""
    pass


@cli.command()
@click.argument('pdf_path', type=click.Path(exists=True))
@click.option('--output', '-o', type=click.Path(), help='Output file path')
@click.option('--format', '-f', type=click.Choice(['markdown', 'json', 'xml']), 
              default='markdown', help='Output format')
@click.option('--config', '-c', type=click.Path(exists=True), 
              default='config.yaml', help='Configuration file path')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def parse(pdf_path: str, output: str, format: str, config: str, verbose: bool):
    """Parse a single PDF file."""
    try:
        # Initialize parser
        parser = SuperGrobidParser(config)
        
        # Set log level
        if verbose:
            parser.logger.setLevel('DEBUG')
        
        # Parse document
        result = parser.parse(pdf_path, format, output)
        
        if result["success"]:
            click.echo(f"✅ Successfully parsed {pdf_path}")
            click.echo(f"📊 Parsing time: {result['parsing_time']:.2f} seconds")
            click.echo(f"📄 Output format: {format}")
            
            if output:
                click.echo(f"💾 Output saved to: {output}")
            
            # Display statistics
            stats = result["statistics"]
            click.echo("\n📈 Statistics:")
            click.echo(f"  • PyMuPDF blocks: {stats['pymupdf_blocks']}")
            click.echo(f"  • Nougat elements: {stats['nougat_elements']}")
            click.echo(f"  • Layout regions: {stats['layout_regions']}")
            click.echo(f"  • Reconciled elements: {stats['reconciled_elements']}")
            click.echo(f"  • Tables: {stats['tables']}")
            click.echo(f"  • Equations: {stats['equations']}")
            click.echo(f"  • References: {stats['references']}")
            
            # Display reconciliation statistics
            recon_stats = stats['reconciliation']
            click.echo(f"  • Hallucination warnings: {recon_stats['hallucination_warnings']}")
            click.echo(f"  • Average confidence: {recon_stats['average_confidence']:.2f}")
            
        else:
            click.echo(f"❌ Failed to parse {pdf_path}: {result.get('error', 'Unknown error')}")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)


@cli.command()
@click.argument('input_dir', type=click.Path(exists=True, file_okay=False))
@click.option('--output-dir', '-o', type=click.Path(), default='output', 
              help='Output directory')
@click.option('--format', '-f', type=click.Choice(['markdown', 'json', 'xml']), 
              default='markdown', help='Output format')
@click.option('--config', '-c', type=click.Path(exists=True), 
              default='config.yaml', help='Configuration file path')
@click.option('--pattern', '-p', default='*.pdf', help='File pattern to match')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def batch(input_dir: str, output_dir: str, format: str, config: str, pattern: str, verbose: bool):
    """Parse multiple PDF files in a directory."""
    try:
        # Find PDF files
        input_path = Path(input_dir)
        pdf_files = list(input_path.glob(pattern))
        
        if not pdf_files:
            click.echo(f"❌ No PDF files found in {input_dir} matching pattern '{pattern}'")
            sys.exit(1)
        
        click.echo(f"📁 Found {len(pdf_files)} PDF files to process")
        
        # Initialize parser
        parser = SuperGrobidParser(config)
        
        # Set log level
        if verbose:
            parser.logger.setLevel('DEBUG')
        
        # Parse batch
        results = parser.parse_batch([str(f) for f in pdf_files], format, output_dir)
        
        # Display results
        successful = sum(1 for r in results if r["success"])
        failed = len(results) - successful
        total_time = sum(r.get("parsing_time", 0) for r in results)
        
        click.echo(f"\n📊 Batch processing completed:")
        click.echo(f"  ✅ Successful: {successful}")
        click.echo(f"  ❌ Failed: {failed}")
        click.echo(f"  ⏱️  Total time: {total_time:.2f} seconds")
        click.echo(f"  📁 Output directory: {output_dir}")
        
        if failed > 0:
            click.echo("\n❌ Failed files:")
            for result in results:
                if not result["success"]:
                    click.echo(f"  • {result['input_file']}: {result.get('error', 'Unknown error')}")
            
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)


@cli.command()
@click.option('--config', '-c', type=click.Path(exists=True), 
              default='config.yaml', help='Configuration file path')
def info(config: str):
    """Display system information and capabilities."""
    try:
        parser = SuperGrobidParser(config)
        stats = parser.get_statistics()
        
        click.echo("🔧 SuperGrobid System Information")
        click.echo("=" * 40)
        click.echo(f"Version: {stats['version']}")
        click.echo(f"Supported formats: {', '.join(stats['supported_formats'])}")
        
        click.echo("\n📦 Component Status:")
        for component, status in stats['components'].items():
            status_icon = "✅" if "Available" in status else "❌"
            click.echo(f"  {status_icon} {component}: {status}")
        
        click.echo("\n⚙️  Configuration:")
        config_info = stats['configuration']
        click.echo(f"  • Similarity method: {config_info['similarity_method']}")
        click.echo(f"  • Similarity threshold: {config_info['similarity_threshold']}")
        click.echo(f"  • Output formats: {', '.join(config_info['output_formats'])}")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)


@cli.command()
@click.argument('pdf_path', type=click.Path(exists=True))
@click.option('--config', '-c', type=click.Path(exists=True), 
              default='config.yaml', help='Configuration file path')
def extract(pdf_path: str, config: str):
    """Extract raw content from PDF without reconciliation."""
    try:
        parser = SuperGrobidParser(config)
        
        click.echo(f"🔍 Extracting raw content from {pdf_path}")
        
        # Extract with PyMuPDF only
        pymupdf_output = parser.pymupdf_extractor.extract(pdf_path)
        
        click.echo(f"📄 PyMuPDF extracted {len(pymupdf_output)} text blocks")
        
        # Display sample blocks
        click.echo("\n📝 Sample text blocks:")
        for i, block in enumerate(pymupdf_output[:5]):
            click.echo(f"  Block {i+1}: {block['text'][:100]}...")
        
        if len(pymupdf_output) > 5:
            click.echo(f"  ... and {len(pymupdf_output) - 5} more blocks")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)


@cli.command()
@click.argument('pdf_path', type=click.Path(exists=True))
@click.option('--config', '-c', type=click.Path(exists=True), 
              default='config.yaml', help='Configuration file path')
def layout(pdf_path: str, config: str):
    """Detect layout regions in PDF."""
    try:
        parser = SuperGrobidParser(config)
        
        click.echo(f"🔍 Detecting layout regions in {pdf_path}")
        
        # Extract layout regions
        layout_output = parser.layout_extractor.extract(pdf_path)
        
        click.echo(f"📐 Detected {len(layout_output)} layout regions")
        
        # Group by type
        regions_by_type = {}
        for region in layout_output:
            region_type = region["type"]
            if region_type not in regions_by_type:
                regions_by_type[region_type] = []
            regions_by_type[region_type].append(region)
        
        click.echo("\n📊 Regions by type:")
        for region_type, regions in regions_by_type.items():
            click.echo(f"  • {region_type}: {len(regions)} regions")
        
        # Display sample regions
        click.echo("\n📍 Sample regions:")
        for i, region in enumerate(layout_output[:3]):
            click.echo(f"  Region {i+1}: {region['type']} (confidence: {region['confidence']:.2f})")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    cli() 