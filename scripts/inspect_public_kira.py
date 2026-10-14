"""Public GET only: inspect model metadata, never use an API key."""
import re
import httpx
from lxml import html

for slug in ('coding-mimo-v2.6-flash', 'deepseek-v4.1-flash', 'glm-5.3-flash'):
    response = httpx.get('https://kiraai.vn/models/'+slug+'/', timeout=25, follow_redirects=True)
    text = response.text
    print(slug, response.status_code)
    tree = html.fromstring(text)
    for row in tree.xpath('//*[contains(@class, "mdp-price-raw")]/../..'):
        print(' '.join(row.text_content().split()))
