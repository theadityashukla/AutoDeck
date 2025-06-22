"""
Output generator for SuperGrobid
Formats reconciled content into different output formats
"""

import logging
from typing import Dict, List, Any, Optional
import json
from pathlib import Path


class OutputGenerator:
    """Generate output in various formats from reconciled content."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger('supergrobid.output')
        
        output_config = config.get('output', {})
        self.include_metadata = output_config.get('include_metadata', True)
        self.include_bbox = output_config.get('include_bbox', False)
    
    def generate_output(self, reconciled_output: List[Dict[str, Any]], 
                       tables: List[Dict[str, Any]], 
                       equations: List[Dict[str, Any]], 
                       references: List[Dict[str, Any]], 
                       output_format: str = "markdown") -> str:
        """
        Generate output in the specified format.
        
        Args:
            reconciled_output: Reconciled content elements
            tables: Parsed tables
            equations: Parsed equations
            references: Parsed references
            output_format: Desired output format ('markdown', 'json', 'xml')
            
        Returns:
            Formatted output string
        """
        self.logger.info(f"Generating {output_format} output")
        
        if output_format == "markdown":
            return self._build_markdown(reconciled_output, tables, equations, references)
        elif output_format == "json":
            return self._build_json(reconciled_output, tables, equations, references)
        elif output_format == "xml":
            return self._build_tei_xml(reconciled_output, tables, equations, references)
        else:
            raise ValueError(f"Unsupported output format: {output_format}")
    
    def _build_markdown(self, reconciled_output: List[Dict[str, Any]], 
                       tables: List[Dict[str, Any]], 
                       equations: List[Dict[str, Any]], 
                       references: List[Dict[str, Any]]) -> str:
        """Build Markdown output."""
        markdown_lines = []
        table_idx = 0
        eq_idx = 0
        
        for element in reconciled_output:
            if element["type"] == "header":
                # Determine header level based on font size or context
                header_level = self._determine_header_level(element)
                markdown_lines.append(f"{'#' * header_level} {element['text']}")
                markdown_lines.append("")
                
            elif element["type"] == "paragraph":
                markdown_lines.append(element["text"])
                markdown_lines.append("")
                
            elif element["type"] == "list":
                # Simple list formatting
                markdown_lines.append(f"- {element['text']}")
                
            elif element["type"] == "table" and table_idx < len(tables):
                table_md = self._format_table_markdown(tables[table_idx])
                markdown_lines.append(table_md)
                markdown_lines.append("")
                table_idx += 1
                
            elif element["type"] == "equation" and eq_idx < len(equations):
                equation_md = self._format_equation_markdown(equations[eq_idx])
                markdown_lines.append(equation_md)
                markdown_lines.append("")
                eq_idx += 1
                
            elif element["type"] == "figure":
                figure_md = self._format_figure_markdown(element)
                markdown_lines.append(figure_md)
                markdown_lines.append("")
                
            elif element["type"] == "orphan":
                # Include orphan text as paragraph
                markdown_lines.append(element["text"])
                markdown_lines.append("")
        
        # Add references section
        if references:
            markdown_lines.append("## References")
            markdown_lines.append("")
            for ref in references:
                ref_text = ref.get("text", "")
                if ref_text:
                    markdown_lines.append(f"- {ref_text}")
            markdown_lines.append("")
        
        return "\n".join(markdown_lines)
    
    def _build_json(self, reconciled_output: List[Dict[str, Any]], 
                   tables: List[Dict[str, Any]], 
                   equations: List[Dict[str, Any]], 
                   references: List[Dict[str, Any]]) -> str:
        """Build JSON output."""
        output_data = {
            "metadata": {
                "total_elements": len(reconciled_output),
                "tables": len(tables),
                "equations": len(equations),
                "references": len(references)
            },
            "content": [],
            "tables": [],
            "equations": [],
            "references": []
        }
        
        # Add content elements
        for element in reconciled_output:
            content_element = {
                "type": element["type"],
                "text": element["text"],
                "page": element["page"],
                "confidence": element.get("confidence", 1.0)
            }
            
            if self.include_bbox:
                content_element["bbox"] = element.get("bbox", [0, 0, 0, 0])
            
            if self.include_metadata:
                content_element["metadata"] = {
                    "blocks": len(element.get("blocks", [])),
                    "hallucination_warning": element.get("hallucination_warning", False)
                }
            
            output_data["content"].append(content_element)
        
        # Add specialized content
        output_data["tables"] = tables
        output_data["equations"] = equations
        output_data["references"] = references
        
        return json.dumps(output_data, indent=2, ensure_ascii=False)
    
    def _build_tei_xml(self, reconciled_output: List[Dict[str, Any]], 
                      tables: List[Dict[str, Any]], 
                      equations: List[Dict[str, Any]], 
                      references: List[Dict[str, Any]]) -> str:
        """Build TEI XML output."""
        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<TEI xmlns="http://www.tei-c.org/ns/1.0">',
            '  <teiHeader>',
            '    <fileDesc>',
            '      <titleStmt>',
            '        <title>Document parsed by SuperGrobid</title>',
            '      </titleStmt>',
            '    </fileDesc>',
            '  </teiHeader>',
            '  <text>',
            '    <body>'
        ]
        
        # Add content elements
        for element in reconciled_output:
            if element["type"] == "header":
                xml_lines.append(f'      <head>{self._escape_xml(element["text"])}</head>')
            elif element["type"] == "paragraph":
                xml_lines.append(f'      <p>{self._escape_xml(element["text"])}</p>')
            elif element["type"] == "list":
                xml_lines.append(f'      <list>')
                xml_lines.append(f'        <item>{self._escape_xml(element["text"])}</item>')
                xml_lines.append(f'      </list>')
        
        xml_lines.extend([
            '    </body>',
            '    <back>',
            '      <listBibl>'
        ])
        
        # Add references
        for ref in references:
            ref_text = ref.get("text", "")
            if ref_text:
                xml_lines.append(f'        <bibl>{self._escape_xml(ref_text)}</bibl>')
        
        xml_lines.extend([
            '      </listBibl>',
            '    </back>',
            '  </text>',
            '</TEI>'
        ])
        
        return "\n".join(xml_lines)
    
    def _determine_header_level(self, element: Dict[str, Any]) -> int:
        """Determine Markdown header level based on element properties."""
        # Check font size if available
        if "blocks" in element and element["blocks"]:
            font_size = element["blocks"][0].get("font_size", 12)
            if font_size > 16:
                return 1
            elif font_size > 14:
                return 2
            elif font_size > 12:
                return 3
            else:
                return 4
        
        # Default to level 2
        return 2
    
    def _format_table_markdown(self, table: Dict[str, Any]) -> str:
        """Format table as Markdown."""
        if not table.get("data"):
            return "<!-- Table data not available -->"
        
        table_data = table["data"]
        if not table_data:
            return "<!-- Empty table -->"
        
        # Convert to Markdown table format
        if isinstance(table_data, list) and table_data:
            # Assume first row contains headers
            headers = list(table_data[0].keys())
            markdown_lines = [f"| {' | '.join(headers)} |"]
            markdown_lines.append(f"| {' | '.join(['---'] * len(headers))} |")
            
            for row in table_data:
                values = [str(row.get(header, '')) for header in headers]
                markdown_lines.append(f"| {' | '.join(values)} |")
            
            return "\n".join(markdown_lines)
        
        return "<!-- Table format not supported -->"
    
    def _format_equation_markdown(self, equation: Dict[str, Any]) -> str:
        """Format equation as Markdown."""
        latex = equation.get("latex", "")
        if latex:
            return f"$${latex}$$"
        return "<!-- Equation not available -->"
    
    def _format_figure_markdown(self, element: Dict[str, Any]) -> str:
        """Format figure as Markdown."""
        text = element.get("text", "")
        if text:
            return f"![Figure]({text})"
        return "<!-- Figure not available -->"
    
    def _escape_xml(self, text: str) -> str:
        """Escape special characters for XML."""
        return (text.replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;")
                   .replace('"', "&quot;")
                   .replace("'", "&apos;"))
    
    def save_output(self, output_content: str, output_path: str) -> None:
        """Save output to file."""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)
        
        self.logger.info(f"Output saved to {output_path}")
    
    def get_output_statistics(self, reconciled_output: List[Dict[str, Any]], 
                            tables: List[Dict[str, Any]], 
                            equations: List[Dict[str, Any]], 
                            references: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Get statistics about the output."""
        stats = {
            "total_elements": len(reconciled_output),
            "text_elements": len([e for e in reconciled_output if e["type"] in ["header", "paragraph", "list"]]),
            "non_text_elements": len([e for e in reconciled_output if e["type"] in ["figure", "table"]]),
            "orphan_elements": len([e for e in reconciled_output if e["type"] == "orphan"]),
            "tables": len(tables),
            "equations": len(equations),
            "references": len(references),
            "hallucination_warnings": len([e for e in reconciled_output if e.get("hallucination_warning", False)]),
            "average_confidence": sum(e.get("confidence", 1.0) for e in reconciled_output) / len(reconciled_output) if reconciled_output else 0
        }
        
        return stats 