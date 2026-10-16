from app.services.chunking import chunk_pages


def test_chunk_pages_preserves_document_page_metadata():
    chunks = chunk_pages(
        [{"page": 3, "text": "permeability porosity saturation pressure gradient", "document_id": "abc"}],
        "reservoir.pdf",
        "abc",
        chunk_size=20,
        chunk_overlap=5,
    )

    assert len(chunks) > 1
    assert chunks[0]["metadata"]["document"] == "reservoir.pdf"
    assert chunks[0]["metadata"]["page"] == 3
    assert chunks[0]["id"].startswith("abc:p3:c0")


def test_chunk_pages_adds_ontology_metadata():
    chunks = chunk_pages(
        [
            {
                "page": 1,
                "text": (
                    "Porosity and permeability control radial flow. "
                    "BHP means bottomhole pressure."
                ),
            }
        ],
        "well-test.pdf",
        "doc1",
        chunk_size=200,
        chunk_overlap=0,
    )

    metadata = chunks[0]["metadata"]

    assert metadata["ontology_version"] == "v0.2"
    assert metadata["domain"] == "petroleum_engineering"
    assert metadata["concept_count"] >= 4
    assert "porosity" in metadata["concepts"]
    assert "absolute_permeability" in metadata["concepts"]
    assert "radial_flow" in metadata["concepts"]
    assert "bottomhole_pressure" in metadata["concepts"]



def test_chunk_pages_keeps_figure_note_complete_and_separate():
    long_analysis = "pressure gradient " * 120
    page_text = (
        "Body paragraph explaining formation pressure.\n\n"
        "[Extracted figure notes]\n"
        "Figure 2: [Figure Note Metadata]\n"
        "image_path: figure2.png\n"
        "title: Appraisal Well RFT Survey\n"
        f"analysis: {long_analysis}\n"
        "x_axis: Pressure\n"
        "y_axis: Depth"
    )

    chunks = chunk_pages(
        [{"page": 10, "text": page_text}],
        "well-test.pdf",
        "doc-figure",
        chunk_size=120,
        chunk_overlap=20,
    )

    body_chunks = [
        chunk for chunk in chunks
        if chunk["metadata"]["chunk_type"] == "text"
    ]
    figure_chunks = [
        chunk for chunk in chunks
        if chunk["metadata"]["chunk_type"] == "figure"
    ]

    assert body_chunks
    assert len(figure_chunks) == 1
    figure_text = figure_chunks[0]["text"]
    assert figure_text.startswith("[Extracted figure notes]")
    assert "[Figure Note Metadata]" in figure_text
    assert "Appraisal Well RFT Survey" in figure_text
    assert "x_axis: Pressure" in figure_text
    assert "y_axis: Depth" in figure_text
    assert len(figure_text) > 120
    assert all("[Figure Note Metadata]" not in chunk["text"] for chunk in body_chunks)


def test_chunk_pages_keeps_multiple_figure_notes_as_individual_chunks():
    page_text = (
        "Related page body.\n"
        "[Extracted figure notes]\n"
        "Figure 1: [Figure Note Metadata]\n"
        "image_path: one.png\n"
        "analysis: first graph\n"
        "Figure 2: [Figure Note Metadata]\n"
        "image_path: two.png\n"
        "analysis: second graph"
    )

    chunks = chunk_pages(
        [{"page": 4, "text": page_text}],
        "doc.pdf",
        "doc-multi-figure",
        chunk_size=80,
        chunk_overlap=10,
    )

    figure_chunks = [
        chunk for chunk in chunks
        if chunk["metadata"]["chunk_type"] == "figure"
    ]
    assert len(figure_chunks) == 2
    assert "one.png" in figure_chunks[0]["text"]
    assert "two.png" not in figure_chunks[0]["text"]
    assert "two.png" in figure_chunks[1]["text"]
    assert all(
        chunk["text"].startswith("[Extracted figure notes]")
        for chunk in figure_chunks
    )


def test_body_chunking_prefers_readable_boundaries():
    text = (
        "Archie equation relates resistivity and saturation. "
        "Formation factor depends on porosity. "
        "Water saturation uses formation water resistivity."
    )

    chunks = chunk_pages(
        [{"page": 1, "text": text}],
        "formation.pdf",
        "doc-boundaries",
        chunk_size=70,
        chunk_overlap=10,
    )

    assert len(chunks) > 1
    assert all(chunk["metadata"]["chunk_type"] == "text" for chunk in chunks)
    assert all(not chunk["text"].startswith("quation") for chunk in chunks)
    assert all(not chunk["text"].startswith("esistivity") for chunk in chunks)



def test_body_chunking_keeps_readable_overlap():
    text = (
        "Archie equation relates resistivity and saturation. "
        "Formation factor depends on porosity. "
        "Water saturation uses formation water resistivity."
    )

    chunks = chunk_pages(
        [{"page": 1, "text": text}],
        "formation.pdf",
        "doc-overlap",
        chunk_size=70,
        chunk_overlap=10,
    )

    texts = [str(chunk["text"]) for chunk in chunks]
    assert len(texts) >= 2
    assert any(
        set(left.split()) & set(right.split())
        for left, right in zip(texts, texts[1:])
    )



def test_overlap_prefers_newline_before_equation_instead_of_mid_equation():
    text = (
        "Equation definitions:\n"
        "Sw = (a * Rw / (phi^m * Rt))^(1/n)\n"
        "Rw = formation water resistivity\n"
        "Rt = true formation resistivity\n"
        "phi = porosity"
    )

    chunks = chunk_pages(
        [{"page": 2, "text": text}],
        "formation.pdf",
        "doc-equation-overlap",
        chunk_size=85,
        chunk_overlap=25,
    )

    texts = [str(chunk["text"]) for chunk in chunks]
    assert len(texts) >= 2
    assert all(
        not chunk.startswith(("* Rt", "Rt))", "water resistivity"))
        for chunk in texts[1:]
    )
    assert any(
        chunk.startswith(("Sw =", "Rw =", "Rt =", "phi ="))
        for chunk in texts[1:]
    )
