from app.services.research_agent import ResearchAgent


def test_structured_figure_note_blocks_ignore_incidental_figure_sentence():
    text = (
        "[Extracted figure notes]\n"
        "Figure 1: [Figure Note Metadata]\n"
        "image_path: one.png\n"
        "analysis: Primary graph.\n"
        "Figure 3: comparison mentioned inside the analysis, not a new note.\n"
        "engineering_meaning: still Figure 1"
    )

    blocks = ResearchAgent._figure_note_blocks(text, {})

    assert len(blocks) == 1
    assert blocks[0][0] == "1"
    assert "Figure 3: comparison" in blocks[0][1]
    assert "engineering_meaning" in blocks[0][1]


def test_structured_figure_note_blocks_split_real_wrappers():
    text = (
        "[Extracted figure notes]\n"
        "Figure 1: [Figure Note Metadata]\n"
        "image_path: one.png\n"
        "analysis: first\n"
        "Figure 2: [Figure Note Metadata]\n"
        "image_path: two.png\n"
        "analysis: second"
    )

    blocks = ResearchAgent._figure_note_blocks(text, {})

    assert [number for number, _ in blocks] == ["1", "2"]
    assert "one.png" in blocks[0][1]
    assert "two.png" not in blocks[0][1]
    assert "two.png" in blocks[1][1]


def test_legacy_figure_note_blocks_remain_supported():
    text = (
        "[Extracted figure notes]\n"
        "Figure 1: pressure graph\n"
        "Figure 2: derivative graph"
    )

    blocks = ResearchAgent._figure_note_blocks(text, {})

    assert [number for number, _ in blocks] == ["1", "2"]



def test_figure_title_falls_back_to_verified_source_caption():
    note = (
        "[Figure Note Metadata]\n"
        "figure_number: 19\n"
        "source_caption: Figure 19 (Upper) - Inasion and Resistivity Profile in water bearing zone.\n"
        "source_caption_verified: true\n"
        "title: null\n"
        "analysis: Visible resistivity profile diagram."
    )

    title = ResearchAgent._figure_title(note, {})

    assert title is not None
    assert title.startswith("(Upper) - Inasion")
    assert not title.startswith("Figure 19")
