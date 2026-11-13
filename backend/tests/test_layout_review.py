"""Synthetic geometric observations, not a real Grammarway acceptance test."""
from app.services.layout_review import visual_candidates


def line(text, x0, y0, x1=None, y1=None):
    return {'text': text, 'bbox': [x0, y0, x1 or x0 + 180, y1 or y0 + 10], 'confidence': 80}


def test_numbered_instruction_and_items_are_one_review_candidate():
    lines = [line('Present Forms', 20, 10), line('Grammar is used for habits.', 20, 25),
             line('9 Complete the text with the correct form.', 20, 60),
             *[line(f'{n}. She ...... (go)', 30, 70 + n * 15) for n in range(1, 11)],
             line('10 Rewrite the sentences.', 20, 250), line('1. The climate is warm.', 30, 270)]
    result = visual_candidates(lines, 600, 800)
    assert len(result['candidates']) == 2
    first = result['candidates'][0]
    assert first['number'] == '9' and len(first['numbered_item_candidates']) == 10
    assert first['needs_review'] and first['bbox'] == [20, 60, 210, 230]
    assert result['candidates'][1]['number'] == '10'
    assert all('Present Forms' not in l['text'] for l in first['lines'])


def test_standalone_number_is_associated_by_position_not_distant_instruction():
    data = [line('1', 20, 40, 30), line('Put the words in the correct groups.', 35, 40, 350),
            line('go   watch   play', 30, 65), line('2', 20, 100, 30),
            line('Rewrite the sentences.', 35, 100, 350), line('1. She goes.', 35, 130)]
    result = visual_candidates(data, 600, 800)
    assert [c['number'] for c in result['candidates']] == ['1', '2']
    assert 'proximity' in result['candidates'][0]['evidence']
    assert all(c['needs_review'] for c in result['candidates'])
    # A number with no nearby instruction is not enough evidence.
    assert not visual_candidates([line('9', 10, 10, 20), line('Write a story.', 400, 200)], 600, 800)['candidates']


def test_full_page_scan_is_not_claimed_as_picture_and_overlap_is_unverified():
    lines = [line('1 Write a sentence.', 20, 40, 200), line('1. The scene', 20, 80, 300)]
    images = [{'bbox': [0, 0, 600, 800]}, {'bbox': [50, 50, 100, 90]}]
    result = visual_candidates(lines, 600, 800, images)
    assert len(result['candidates'][0]['image_candidates']) == 1
    assert result['candidates'][0]['image_candidates'][0]['relationship'] == 'overlaps_region_unverified'
    assert 'CROSS_PAGE_GROUPING_NOT_AVAILABLE' in result['warnings']


def test_synthetic_right_column_speaking_dialogue_and_rewrite_with_theory_at_left():
    # Deliberately synthetic coordinates / transcriptions inspired by the supplied
    # annotated picture; not output from OCR and not an acceptance count.
    data = [line('Too/Enough', 20, 30, 160), line('8', 310, 40, 320),
            line('In pairs, ask and answer questions using', 325, 40, 550),
            line('the prompts below, as in the example.', 325, 52, 550),
            line('Too comes before adjectives.', 20, 65, 200),
            line('S1: Is the film too scary?', 315, 70, 550),
            line('S2: Yes, it is.', 315, 82, 550),
            line('1 film / scary / watch', 315, 95, 550),
            line('2 report / boring / read', 315, 110, 550),
            line('9', 310, 130, 320),
            line('Complete the sentences with too or enough.', 325, 130, 550),
            line('1 A: Would you like to come?', 315, 145, 550),
            line('B: Oh no, I am too tired.', 330, 157, 550),
            line('Examples of the rule.', 20, 160, 200),
            line('2 A: Can you reach it?', 315, 175, 550),
            line('B: No, I am not ......', 330, 187, 550),
            line('10 Rewrite the sentences using too.', 310, 210, 550),
            line('1 This music is so slow.', 315, 225, 550)]
    result = visual_candidates(data, 600, 800)
    candidates = result['candidates']
    assert [c['number'] for c in candidates] == ['8', '9', '10']
    assert [len(c['numbered_item_candidates']) for c in candidates] == [2, 2, 1]
    assert candidates[1]['numbered_item_candidates'][0]['continuation_lines'] == ['B: Oh no, I am too tired.']
    assert 'the prompts below' in ' '.join(l['text'] for l in candidates[0]['lines'])
    assert 'Too comes' not in ' '.join(l['text'] for c in candidates for l in c['lines'])
    assert all(c['needs_review'] for c in candidates)
