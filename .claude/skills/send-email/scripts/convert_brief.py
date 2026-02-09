import re
import html

class MarkdownToHtml:
    def __init__(self):
        self.html = ""
        self.in_list = False
        self.list_type = None  # 'ul' or 'ol'

    def convert(self, markdown_text):
        # normalize line endings
        markdown_text = markdown_text.replace('\r\n', '\n')
        
        # Process code blocks first to avoid interference
        markdown_text, self.code_blocks = self._extract_code_blocks(markdown_text)
        
        lines = markdown_text.split('\n')
        html_lines = []
        
        # Reset state
        self.in_list = False
        self.list_type = None
        
        # Pre-process for tables (simple robust approach)
        lines = self._process_tables(lines)

        for line in lines:
            # Check for list items first to handle state
            if self._is_list_item(line):
                html_lines.append(self._process_list_item(line))
            else:
                # Close list if open
                if self.in_list:
                    html_lines.append(f"</{self.list_type}>")
                    self.in_list = False
                    self.list_type = None
                
                html_lines.append(self._process_line(line))
        
        if self.in_list:
            html_lines.append(f"</{self.list_type}>")

        body_content = '\n'.join(html_lines)
        
        # Restore code blocks
        body_content = self._restore_code_blocks(body_content)
        
        return self._wrap_in_template(body_content)

    def _extract_code_blocks(self, text):
        code_blocks = {}
        def replace(match):
            key = f"CODE_BLOCK_{len(code_blocks)}"
            lang = match.group(1).strip() if match.group(1) else ''
            code = match.group(2)
            # Basic html escaping for code content
            code = html.escape(code)
            code_blocks[key] = f'<pre><code class="language-{lang}">{code}</code></pre>'
            return key
        
        # Match ```lang ... ```
        pattern = r'```(\w*)\n(.*?)```'
        text = re.sub(pattern, replace, text, flags=re.DOTALL)
        return text, code_blocks

    def _restore_code_blocks(self, text):
        for key, html_block in self.code_blocks.items():
            text = text.replace(key, html_block)
        return text

    def _process_tables(self, lines):
        # Identify table blocks and convert them before line-by-line processing
        new_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Detect table start: Pipe char present, and next line looks like separator
            if '|' in line and i + 1 < len(lines) and re.match(r'^\s*\|?[\s-]+\|[\s-]+\|?.*$', lines[i+1]):
                # Table detected
                table_html = ["<div class='table-wrapper'><table>"]
                
                # Header
                headers = [h.strip() for h in line.strip('|').split('|')]
                table_html.append("<thead><tr>" + "".join([f"<th>{h}</th>" for h in headers]) + "</tr></thead>")
                
                table_html.append("<tbody>")
                i += 2 # Skip header and separator
                
                # Rows
                while i < len(lines) and '|' in lines[i]:
                    row_cells = [c.strip() for c in lines[i].strip('|').split('|')]
                    # simple fix for empty cells at ends if split creates them
                    if len(row_cells) > len(headers): row_cells = row_cells[:len(headers)] 
                    
                    table_html.append("<tr>" + "".join([f"<td>{self._format_inline(c)}</td>" for c in row_cells]) + "</tr>")
                    i += 1
                
                table_html.append("</tbody></table></div>")
                new_lines.append("".join(table_html))
            else:
                new_lines.append(line)
                i += 1
        return new_lines

    def _is_list_item(self, line):
        return re.match(r'^\s*([-*]|\d+\.)\s+', line)

    def _process_list_item(self, line):
        match = re.match(r'^\s*([-*]|\d+\.)\s+(.*)', line)
        marker = match.group(1)
        content = match.group(2)
        
        current_type = 'ol' if marker[0].isdigit() else 'ul'
        output = []
        
        if not self.in_list:
            self.in_list = True
            self.list_type = current_type
            output.append(f"<{self.list_type}>")
        elif self.list_type != current_type:
            # Switch list type (rare in simple md but possible)
            output.append(f"</{self.list_type}>")
            self.list_type = current_type
            output.append(f"<{self.list_type}>")
            
        output.append(f"<li>{self._format_inline(content)}</li>")
        return "".join(output)

    def _process_line(self, line):
        # Empty lines
        if not line.strip():
            return ""

        # HTML injection (for tables processed earlier)
        if line.startswith("<div class='table-wrapper'>"):
            return line

        # Headers
        header_match = re.match(r'^(#{1,6})\s+(.*)', line)
        if header_match:
            level = len(header_match.group(1))
            text = header_match.group(2)
            return f"<h{level}>{self._format_inline(text)}</h{level}>"

        # Blockquotes
        if line.startswith('> '):
            return f"<blockquote>{self._format_inline(line[2:])}</blockquote>"

        # Horizontal Rule
        if re.match(r'^(-{3,}|\*{3,})$', line.strip()):
            return "<hr>"

        # Paragraph
        return f"<p>{self._format_inline(line)}</p>"

    def _format_inline(self, text):
        # Bold
        text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
        # Italic
        text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
        # Code
        text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
        # Links
        text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', text)
        return text

    def _wrap_in_template(self, body_content):
        css = """
        :root {
            --primary-color: #2563eb;
            --text-color: #1e293b;
            --text-light: #64748b;
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --border-color: #e2e8f0;
            --code-bg: #1e1e1e;
            --accent-color: #3b82f6;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
            background-color: var(--bg-color);
            color: var(--text-color);
            line-height: 1.7;
            margin: 0;
            padding: 40px 20px;
            -webkit-font-smoothing: antialiased;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: var(--card-bg);
            padding: 48px;
            border-radius: 12px;
            box-shadow: 0 10px 30px -10px rgba(0,0,0,0.08);
            border: 1px solid rgba(255,255,255,0.5);
        }
        
        /* Typography */
        h1 {
            color: #0f172a;
            font-size: 32px;
            font-weight: 800;
            letter-spacing: -0.025em;
            margin-bottom: 24px;
            margin-top: 0;
            padding-bottom: 16px;
            border-bottom: 2px solid var(--border-color);
        }
        h2 {
            color: #1e293b;
            font-size: 24px;
            font-weight: 700;
            margin-top: 48px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
        }
        h2::before {
            content: '';
            display: inline-block;
            width: 6px;
            height: 24px;
            background: linear-gradient(to bottom, var(--primary-color), var(--accent-color));
            margin-right: 12px;
            border-radius: 3px;
        }
        h3 {
            color: #334155;
            font-size: 20px;
            font-weight: 600;
            margin-top: 32px;
            margin-bottom: 12px;
        }
        p {
            margin-bottom: 1.25em;
            color: #334155;
        }
        
        /* Links & Interactive */
        a {
            color: var(--primary-color);
            text-decoration: none;
            border-bottom: 1px solid transparent;
            transition: border-color 0.2s;
        }
        a:hover {
            border-bottom-color: var(--primary-color);
        }
        
        /* Lists */
        ul, ol {
            margin-bottom: 24px;
            padding-left: 28px;
            color: #334155;
        }
        li {
            margin-bottom: 8px;
            padding-left: 4px;
        }
        li::marker {
            color: var(--text-light);
        }
        
        /* Blockquote */
        blockquote {
            background-color: #f1f5f9;
            border-left: 5px solid var(--accent-color);
            margin: 32px 0;
            padding: 16px 24px;
            border-radius: 0 8px 8px 0;
            color: #475569;
            font-style: italic;
            position: relative;
        }
        
        /* Tables */
        .table-wrapper {
            overflow-x: auto;
            margin: 32px 0;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.95em;
            background: white;
        }
        th {
            background-color: #f8fafc;
            color: #475569;
            font-weight: 600;
            text-align: left;
            padding: 12px 16px;
            border-bottom: 2px solid var(--border-color);
        }
        td {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border-color);
            color: #334155;
        }
        tr:last-child td {
            border-bottom: none;
        }
        tr:hover td {
            background-color: #f8fafc;
        }
        
        /* Code */
        code {
            font-family: 'JetBrains Mono', 'Fira Code', Consolas, Monaco, monospace;
            font-size: 0.9em;
            background-color: #f1f5f9;
            padding: 2px 6px;
            border-radius: 4px;
            color: #dc2626;
        }
        pre {
            background-color: var(--code-bg);
            padding: 20px;
            border-radius: 8px;
            overflow-x: auto;
            margin: 24px 0;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.3);
        }
        pre code {
            background-color: transparent;
            color: #e2e8f0;
            padding: 0;
            font-size: 0.9em;
            display: block;
        }
        
        /* Utility */
        hr {
            border: 0;
            height: 1px;
            background: linear-gradient(to right, transparent, var(--border-color), transparent);
            margin: 48px 0;
        }
        strong {
            color: #0f172a;
            font-weight: 600;
        }
        .footer {
            margin-top: 60px;
            text-align: center;
            font-size: 13px;
            color: #94a3b8;
            border-top: 1px solid var(--border-color);
            padding-top: 20px;
        }
        """
        
        html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Strategic Insight Brief</title>
    <style>
    {css}
    </style>
</head>
<body>
    <div class="container">
        {body_content}
        <div class="footer">
            <p>Generated by Intelligence Insight Agent &bull; Confidential</p>
        </div>
    </div>
</body>
</html>
"""
        return html_template

def convert_file(input_path, output_path=None):
    with open(input_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    converter = MarkdownToHtml()
    html_content = converter.convert(md_content)
    
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        return output_path
    return html_content

if __name__ == "__main__":
    import sys
    import os
    
    if len(sys.argv) < 2:
        print("Usage: python convert_brief.py <input_md_file> [output_html_file]")
        sys.exit(1)
        
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.md', '.html')
    
    convert_file(input_file, output_file)
    print(f"Successfully converted {input_file} to {output_file}")
