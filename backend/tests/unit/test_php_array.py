"""PHP var_export / short-array parser tests (offline adapter anti-corruption layer)."""

import pytest

from rfq_copilot.adapters.vacuum_b2b_offline.php_array import (
    PhpParseError,
    extract_literal_span,
    parse_php_value,
)


def test_parses_long_array_syntax_with_int_keys() -> None:
    text = """<?php
return array (
  0 => array ( 'name' => 'demo A', 'price' => 3000, 'spec_speed' => 6.0 ),
  1 => array ( 'name' => 'demo B', 'images' => NULL ),
);"""
    data = parse_php_value(text)
    assert isinstance(data, list)
    assert data[0]["name"] == "demo A"
    assert data[0]["price"] == 3000
    assert data[0]["spec_speed"] == 6.0
    assert data[1]["images"] is None


def test_parses_short_array_syntax_with_strings_and_bools() -> None:
    text = "return [ ['slug' => 'demo-x', 'priority' => true, 'brief' => ''], ['priority' => false] ];"
    data = parse_php_value(text)
    assert data[0]["priority"] is True
    assert data[1]["priority"] is False
    assert data[0]["brief"] == ""


def test_handles_escaped_quotes_and_backslashes() -> None:
    text = r"return [ 'note' => '包含 \'引号\' 与 \\ 反斜杠' ];"
    data = parse_php_value(text)
    assert isinstance(data, dict)
    assert data["note"] == "包含 '引号' 与 \\ 反斜杠"


def test_skips_php_comments_inside_arrays() -> None:
    text = """return [
        /* ── 旗舰模板开关 ── */
        'is_flagship_template' => true, // trailing comment
        'hero' => 'demo',
    ];"""
    data = parse_php_value(text)
    assert data["is_flagship_template"] is True
    assert data["hero"] == "demo"


def test_negative_and_float_numbers() -> None:
    data = parse_php_value("return [ -12, 3.14, 1e3, -0.5 ];")
    assert data == [-12, 3.14, 1000.0, -0.5]


def test_unterminated_array_raises_with_position() -> None:
    with pytest.raises(PhpParseError):
        parse_php_value("return array ( 0 => array ( 'a' => 1 );")


def test_extract_literal_span_via_function_marker() -> None:
    text = """<?php
class Seeder
{
    /** 注释 */
    private function industries(): array
    {
        return [
            ['slug' => 'demo-food', 'name' => 'demo 食品', 'categories' => [
                ['slug' => 'demo-freeze', 'varieties' => [ ['slug' => 'demo-fruit'] ]],
            ]],
        ];
    }
}"""
    literal = extract_literal_span(text, "private function industries(): array")
    data = parse_php_value(literal)
    assert data[0]["slug"] == "demo-food"
    assert data[0]["categories"][0]["varieties"][0]["slug"] == "demo-fruit"


def test_extract_ignores_brackets_inside_strings() -> None:
    text = "return [ 'title' => '数组字面量 [ 不是边界 ]', 'ok' => true ];"
    literal = extract_literal_span(text, "return")
    data = parse_php_value(literal)
    assert data["ok"] is True
    assert data["title"] == "数组字面量 [ 不是边界 ]"


def test_missing_marker_raises() -> None:
    with pytest.raises(PhpParseError):
        extract_literal_span("nothing here", "private function nope(): array")
