from edit_vocab import audio_fades_for_segment, AUDIO_FADE_SECONDS


def test_legacy_boundary_fades_when_fields_omitted():
    fin, fout = audio_fades_for_segment(
        None, None, index=1, piece_count=3, seg_duration=2.0
    )
    assert fin == AUDIO_FADE_SECONDS
    assert fout == AUDIO_FADE_SECONDS
    fin0, fout2 = audio_fades_for_segment(
        None, None, index=0, piece_count=3, seg_duration=2.0
    )
    assert fin0 == 0.0
    assert fout2 == AUDIO_FADE_SECONDS
    _, fout_last = audio_fades_for_segment(
        None, None, index=2, piece_count=3, seg_duration=2.0
    )
    assert fout_last == 0.0


def test_explicit_per_clip_fades():
    fin, fout = audio_fades_for_segment(
        0.5, 0.1, index=0, piece_count=1, seg_duration=2.0
    )
    assert fin == 0.5
    assert fout == 0.1
