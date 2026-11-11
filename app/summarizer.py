"""Interchangeable summary providers; local is the default."""
import json
import os
import urllib.request


class LocalSummarizer:
    def summarize(self, order):
        return (f"Scope: {order['note']}\nAmount: USD ${order['amount']}\n"
                "Terms: Due on receipt after approval and invoicing. Please review the scope and amount before deciding.")


class HTTPSummarizer:
    def __init__(self, url, key, model):
        self.url, self.key, self.model = url, key, model

    def summarize(self, order):
        body = {'model': self.model, 'messages': [
            {'role': 'system', 'content': 'Write a concise client-facing change order scope from the supplied note. Do not invent facts, prices or terms. Return scope text only.'},
            {'role': 'user', 'content': order['note']}]}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method='POST',
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.key})
        with urllib.request.urlopen(req, timeout=30) as response:
            text = json.load(response)['choices'][0]['message']['content'].strip()
        if not text or len(text) > 3000:
            raise ValueError('Summary provider returned an empty or oversized response.')
        return f"Scope: {text}\nAmount: USD ${order['amount']}\nTerms: Due on receipt after approval and invoicing. Please review the scope and amount before deciding."


def configured_summarizer():
    values = [os.environ.get(k, '').strip() for k in ('AI_BASE_URL', 'AI_API_KEY', 'AI_MODEL')]
    if any(values) and not all(values):
        raise ValueError('Set AI_BASE_URL, AI_API_KEY and AI_MODEL together.')
    return HTTPSummarizer(values[0].rstrip('/') + '/chat/completions', values[1], values[2]) if all(values) else LocalSummarizer()
