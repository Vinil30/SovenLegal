from openai import OpenAI
import os
from dotenv import load_dotenv
import json
from pathlib import Path

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL')
OPENAI_MODEL = os.getenv('OPENAI_MODEL')


class DocumentReferenceGenerator:
    def __init__(self, api_key=OPENAI_API_KEY):
        self.api_key = api_key

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=OPENAI_BASE_URL
        )

        self.model = OPENAI_MODEL

    def generate_reference_html(
        self,
        doc_name,
        query_context,
        required_elements=None,
        visual_reference=None
    ):
        """
        Generate HTML reference document for a specific document type

        Args:
            doc_name (str): Name of the document
            query_context (str): The legal query context
            required_elements (list): List of required elements
            visual_reference (dict): Visual reference information

        Returns:
            str: Generated HTML content
        """

        system_prompt = f"""
You are an expert legal document reference generator for legal documents.

Document Type: {doc_name}
Legal Query Context: {query_context}

Required Elements (if available):
{json.dumps(required_elements or [], indent=2)}

Visual Reference Information (if available):
{json.dumps(visual_reference or {}, indent=2)}

Generate a comprehensive HTML visual reference similar to image or how it looks if seen in direct using stylings for "{doc_name}" that includes Sample Format/Template

Requirements for HTML output:
- Use modern, clean CSS styling
- Include proper headings, sections, and formatting
- Add visual indicators (checkmarks, icons, etc.)
- Make it printer-friendly
- Include hover effects and interactive elements
- Use Indian legal document standards
- Add color coding for different sections
- Make it comprehensive but easy to read

Return ONLY the complete HTML document with embedded CSS and any necessary JavaScript.
The HTML should be a standalone, complete document that can be saved as doc_reference.html.
"""

        try:

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": system_prompt
                    }
                ],
                temperature=0.7
            )

            html_content = response.choices[0].message.content

            # Clean up the response to ensure it's valid HTML
            html_content = self._clean_html_response(html_content)

            return html_content

        except Exception as e:
            return self._generate_error_html(doc_name, str(e))

    def save_reference_html(
        self,
        html_content,
        output_path="templates/doc_reference.html"
    ):
        """
        Save the generated HTML content to a file

        Args:
            html_content (str): The HTML content to save
            output_path (str): Path where to save the file
        """

        try:
            # Ensure the directory exists
            Path(output_path).parent.mkdir(
                parents=True,
                exist_ok=True
            )

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            return True

        except Exception as e:
            print(f"Error saving HTML file: {e}")
            return False

    def _clean_html_response(self, html_content):
        """Clean and validate HTML response"""

        # Remove markdown code block indicators
        html_content = html_content.strip()

        if html_content.startswith("```html"):
            html_content = html_content[7:]

        if html_content.startswith("```"):
            html_content = html_content[3:]

        if html_content.endswith("```"):
            html_content = html_content[:-3]

        # Ensure proper HTML declaration
        if not html_content.strip().startswith("<!DOCTYPE html>"):
            html_content = "<!DOCTYPE html>\n" + html_content

        return html_content.strip()

    def _generate_error_html(self, doc_name, error_message):
        """Generate fallback HTML in case of errors"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Document Reference - {doc_name}</title>

    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f8f9fa;
        }}

        .error-container {{
            background: #f8d7da;
            border: 1px solid #f5c6cb;
            color: #721c24;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}

        .error-icon {{
            font-size: 48px;
            margin-bottom: 20px;
        }}
    </style>
</head>

<body>
    <div class="error-container">
        <div class="error-icon">⚠️</div>

        <h2>Reference Generation Error</h2>

        <p>
            Unable to generate reference for:
            <strong>{doc_name}</strong>
        </p>

        <p>
            <em>Error: {error_message}</em>
        </p>

        <p>
            Please try again or contact support if the issue persists.
        </p>
    </div>
</body>
</html>"""


# Flask route handler function
def handle_document_reference_request(doc_name, query_data):
    """
    Handle the document reference generation request

    Args:
        doc_name (str): Name of the document
        query_data (dict): Query data from database

    Returns:
        dict: Response with success status and file path
    """

    try:
        # Initialize generator
        generator = DocumentReferenceGenerator()

        # Extract information from query data
        query_context = query_data.get('text', '')

        # Find the specific document and its details
        documents = query_data.get('documents', [])

        required_elements = None
        visual_reference = None

        # If documents contain detailed objects
        if documents and isinstance(documents[0], dict):

            for doc in documents:

                if doc.get('name') == doc_name or doc == doc_name:
                    required_elements = doc.get(
                        'required_elements',
                        []
                    )

                    visual_reference = doc.get(
                        'visual_reference',
                        {}
                    )

                    break

        # Generate HTML reference
        html_content = generator.generate_reference_html(
            doc_name=doc_name,
            query_context=query_context,
            required_elements=required_elements,
            visual_reference=visual_reference
        )

        # Save generated HTML
        success = generator.save_reference_html(html_content)

        if success:
            return {
                'success': True,
                'message': f'Reference generated successfully for {doc_name}',
                'file_path': 'templates/doc_reference.html'
            }

        else:
            return {
                'success': False,
                'message': 'Failed to save reference file',
                'error': 'File save error'
            }

    except Exception as e:
        return {
            'success': False,
            'message': f'Failed to generate reference for {doc_name}',
            'error': str(e)
        }