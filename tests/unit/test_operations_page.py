import operations
import operations_page
import baseline_web


def test_operations_uses_one_action_selector_and_shared_form():
    page = operations_page.render_operations_page(operations.OPERATIONS, []).decode()
    assert '<select id="operation-choice"' in page
    assert page.count('id="operation-run"') == 1
    assert 'id="operation-description"' in page
    assert 'id="operation-schedules"' in page
    assert 'id="operation-history"' in page


def test_operations_renders_real_schedules_and_history():
    page = operations_page.render_operations_page(operations.OPERATIONS,
        [{'op':'backup_verify','every_hours':24,'params':{},'last_run':None}],
        history=[{'op':'backup_verify','source':'schedule','started':1,'outcome':'applied','detail':'<checked>'}]).decode()
    assert 'backup verify' in page and 'Never run' in page
    assert 'schedule' in page and '&lt;checked&gt;' in page


def test_shared_nav_is_styled_independently_of_page():
    page = baseline_web._with_nav(b'<html><head></head><body>test</body></html>', '/operations').decode()
    assert 'baseline-shell-style' in page
    assert 'flex-wrap:wrap' in page
