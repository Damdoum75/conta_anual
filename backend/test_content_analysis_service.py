import unittest

from app.services.content_analysis_service import extract_from_html, analyze_text


class ContentAnalysisServiceTests(unittest.TestCase):
    def test_extract_from_html(self):
        html = """
        <html>
          <head>
            <title>Example Title</title>
            <meta name="description" content="Example description.">
            <meta property="og:title" content="OG Title">
            <meta property="og:description" content="OG description">
          </head>
          <body>
            <h1>Hello World</h1>
            <p>Automation PLC SCADA #industrie50</p>
          </body>
        </html>
        """
        extracted = extract_from_html("https://example.com", html)
        self.assertEqual(extracted.title, "Example Title")
        self.assertEqual(extracted.description, "Example description.")
        self.assertEqual(extracted.og_title, "OG Title")
        self.assertEqual(extracted.og_description, "OG description")
        self.assertIn("Hello World", extracted.text)

    def test_analyze_text_arabic(self):
        analysis = analyze_text("هذا اختبار بسيط #صناعة")
        self.assertEqual(analysis["language"], "ar")
        self.assertIn("صناعة", analysis["hashtags"])


if __name__ == "__main__":
    unittest.main()

