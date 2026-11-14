"""Untrusted AI picture hints never replace originals or invalidate the whole exercise."""
import json
from app.services.ai.vision_topic import Question
from tests.test_browser_ocr import setup_scan
from tests.test_vision_map_preview import setup, topic_output


def test_bad_regions_are_dropped_without_losing_question():
    base = {'number': '2', 'prompt': '...', 'options': [], 'evidence_pages': [2]}
    valid = {'page': 2, 'bbox': [100, 200, 300, 400]}
    assert Question.model_validate({**base, 'picture': valid}).picture.page == 2
    for picture in (None, {'page': 2, 'bbox': [300, 1, 200, 20]},
                    {'page': 2, 'bbox': [-1, 1, 100, 200]}, {'page': 2, 'bbox': [1, 1, 1001, 200]},
                    {'page': '2', 'bbox': [1, 1, 2, 2]}, {'page': 2, 'bbox': [1, 2, 3]},
                    {'page': 2, 'bbox': [1, 1, float('nan'), 4]}, 'bad'):
        q = Question.model_validate({**base, 'picture': picture})
        assert q.picture is None and q.number == '2'
    assert Question.model_validate(base).picture is None


def test_region_page_must_be_selected_and_cited(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    output = json.loads(topic_output())
    questions = output['exercises'][0]['questions']
    questions[0]['picture'] = {'page': 2, 'bbox': [100, 200, 300, 400]}
    questions[1]['picture'] = {'page': 1, 'bbox': [100, 200, 300, 400]}  # selected but not question evidence
    questions[2]['picture'] = {'page': 3, 'bbox': [100, 200, 300, 400]}  # not selected
    questions[3]['picture'] = {'page': 2, 'bbox': [400, 200, 300, 400]}  # invalid
    provider = setup(monkeypatch, [json.dumps(output)])
    monkeypatch.setattr('app.services.ai.vision_topic.get_provider', lambda: provider)
    res = client.post(f'/api/v1/books/{book}/vision-topic/preview', headers=h,
                      json={'page_numbers': [1, 2], 'topic': '', 'consent_images_to_provider': True})
    assert res.status_code == 200, res.text
    qs = res.json()['exercises'][0]['questions']
    assert qs[0]['picture'] == {'page': 2, 'bbox': [100, 200, 300, 400]}
    assert all(qs[i]['picture'] is None for i in (1, 2, 3))
    assert len(qs) == 10 and len(provider.calls) == 1
