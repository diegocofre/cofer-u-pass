from cofer_u_pass.domain.blocks import block_to_text
from cofer_u_pass.domain.models import Block


def test_plain_text_does_not_duplicate_live_chatgpt_paragraph_tree():
    block = Block(
        type="document",
        children=[
            Block(
                type="unknown",
                attrs={"tag": "div"},
                children=[
                    Block(
                        type="unknown",
                        attrs={"tag": "div"},
                        children=[
                            Block(
                                type="paragraph",
                                text="COFER-U-PASS-OK",
                                children=[Block(type="text", text="COFER-U-PASS-OK")],
                            )
                        ],
                    )
                ],
            )
        ],
    )

    assert block_to_text(block) == "COFER-U-PASS-OK"


def test_plain_text_uses_children_for_mixed_inline_paragraph_content():
    block = Block(
        type="paragraph",
        text="Hello !",
        children=[
            Block(type="text", text="Hello "),
            Block(type="unknown", attrs={"tag": "strong"}, children=[Block(type="text", text="world")]),
            Block(type="text", text="!"),
        ],
    )

    assert block_to_text(block) == "Hello world!"


def test_plain_text_falls_back_to_container_text_without_children():
    assert block_to_text(Block(type="paragraph", text="fallback")) == "fallback"
