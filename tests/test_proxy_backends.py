# tests/test_proxy_backends.py
# Unit tests for PotaProxy backends — no radio software required.
# Run with: python3 build.py test
import sys, os, time, socket, pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from PotaProxy import MacLoggerDXBackend, RigctldBackend, Log4OmBackend


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mldx_tune_capture(note='', callsign='W1AW', freq_hz=14074000, mode='FT8'):
    """Run MacLoggerDXBackend.tune() with mocked subprocess; return -e args."""
    backend = MacLoggerDXBackend()
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
        backend.tune(freq_hz, mode, callsign=callsign, note=note)
        cmd = mock_run.call_args[0][0]
        return [cmd[i + 1] for i, a in enumerate(cmd) if a == '-e']


def _rigctld_tune_capture(freq_hz=14074000, mode='FT8'):
    """Run RigctldBackend.tune() with mocked socket; return commands sent."""
    backend = RigctldBackend()
    mock_sock = MagicMock()
    mock_sock.recv.return_value = b'RPRT 0\n'
    mock_sock.__enter__ = lambda s: s
    mock_sock.__exit__ = MagicMock(return_value=False)
    with patch.object(backend, '_connect', return_value=mock_sock):
        backend.tune(freq_hz, mode)
    return [c[0][0].decode('ascii').strip() for c in mock_sock.sendall.call_args_list]


# ── MacLoggerDX: note sanitization ───────────────────────────────────────────

@pytest.mark.parametrize("note", [
    'POTA BY-0140 Чыстая дуброва Nature Reserve',    # Cyrillic
    'POTA CN-0645 河南新乡新乡市人民公园 Regional Park',  # Chinese
    'POTA DE-0083 Märkische Schweiz Nature Park',     # German umlaut
])
def test_non_ascii_stripped(note):
    lines = _mldx_tune_capture(note=note)
    note_line = next(l for l in lines if 'setNOTE' in l)
    assert note_line.isascii()


def test_embedded_quotes_stripped():
    lines = _mldx_tune_capture(note='POTA BY-0140 "Язненская" Nature Reserve')
    note_line = next(l for l in lines if 'setNOTE' in l)
    assert '"' not in note_line[len('setNOTE "'):-1]


@pytest.mark.parametrize("note", [
    'Чыстая дуброва',  # all non-ASCII
    '',                 # empty
    '   ',              # whitespace only
])
def test_bad_note_omitted(note):
    lines = _mldx_tune_capture(note=note)
    assert not any('setNOTE' in l for l in lines)


def test_clean_ascii_preserved():
    lines = _mldx_tune_capture(note='POTA US-1234 Yosemite National Park')
    note_line = next(l for l in lines if 'setNOTE' in l)
    assert 'Yosemite National Park' in note_line


def test_ref_with_hyphen_preserved():
    lines = _mldx_tune_capture(note='POTA US-0001')
    note_line = next(l for l in lines if 'setNOTE' in l)
    assert 'POTA US-0001' in note_line


# ── rigctld: split command ────────────────────────────────────────────────────

def test_split_off_command_sent():
    assert 'S 0 VFOA' in _rigctld_tune_capture()


def test_split_off_sent_after_mode():
    cmds = _rigctld_tune_capture()
    assert cmds.index('S 0 VFOA') > next(i for i, c in enumerate(cmds) if c.startswith('M '))


def test_frequency_command_format():
    assert 'F 14074000' in _rigctld_tune_capture(freq_hz=14074000)


def test_ft8_mapped_to_pktusb():
    assert any(c.startswith('M PKTUSB') for c in _rigctld_tune_capture(mode='FT8'))


def test_cw_passed_through():
    assert any(c.startswith('M CW') for c in _rigctld_tune_capture(mode='CW'))


# ── Log4OM: UDP XML datagrams ─────────────────────────────────────────────────

def _log4om_tune_capture(freq_hz=14074000, mode='FT8', callsign=''):
    """Run Log4OmBackend.tune() with mocked socket; return list of decoded XML strings sent."""
    backend = Log4OmBackend()
    sent = []
    mock_sock = MagicMock()
    mock_sock.__enter__ = lambda s: s
    mock_sock.__exit__ = MagicMock(return_value=False)
    mock_sock.sendto.side_effect = lambda data, addr: sent.append(data.decode('utf-8'))
    with patch('socket.socket', return_value=mock_sock):
        backend.tune(freq_hz, mode, callsign=callsign)
    return sent


def test_log4om_set_tx_frequency_sent():
    sent = _log4om_tune_capture(freq_hz=14074000)
    assert any('SetTxFrequency' in s for s in sent)


def test_log4om_frequency_value_correct():
    sent = _log4om_tune_capture(freq_hz=14074000)
    freq_msg = next(s for s in sent if 'SetTxFrequency' in s)
    assert '<Frequency>14074000</Frequency>' in freq_msg


def test_log4om_xml_has_message_id():
    sent = _log4om_tune_capture()
    assert all('<MessageId>' in s for s in sent)


def test_log4om_callsign_sent_when_provided():
    sent = _log4om_tune_capture(callsign='W1AW')
    assert any('SetCallsign' in s for s in sent)


def test_log4om_callsign_value_correct():
    sent = _log4om_tune_capture(callsign='W1AW')
    call_msg = next(s for s in sent if 'SetCallsign' in s)
    assert '<Callsign>W1AW</Callsign>' in call_msg


def test_log4om_callsign_not_sent_when_empty():
    sent = _log4om_tune_capture(callsign='')
    assert not any('SetCallsign' in s for s in sent)


def test_log4om_set_mode_not_sent():
    # SetMode is broken in Log4OM — verify we never send it
    sent = _log4om_tune_capture(mode='FT8')
    assert not any('SetMode' in s for s in sent)


# ── Log4OM: ping / heartbeat ──────────────────────────────────────────────────

def _make_log4om_backend():
    """Return a Log4OmBackend with the heartbeat listener thread suppressed."""
    with patch('threading.Thread'):
        backend = Log4OmBackend(heartbeat_port=0)
    return backend


def test_log4om_ping_ok_when_no_heartbeat_ever():
    # No heartbeat received yet → conservative ok (user may not have it enabled)
    backend = _make_log4om_backend()
    assert backend.ping() == "ok"


def test_log4om_ping_ok_when_heartbeat_recent():
    backend = _make_log4om_backend()
    backend._ever_received_heartbeat = True
    backend._last_heartbeat = time.monotonic()
    assert backend.ping() == "ok"


def test_log4om_ping_raises_when_heartbeat_stale():
    backend = _make_log4om_backend()
    backend._ever_received_heartbeat = True
    backend._last_heartbeat = time.monotonic() - 20  # 20s ago — past 15s timeout
    with pytest.raises(ConnectionRefusedError):
        backend.ping()


def test_log4om_ping_ok_via_tasklist_when_running():
    backend = _make_log4om_backend()
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='"L4ONG.exe","1234","Console","1","10,000 K"')
        assert backend.ping() == "ok"


def test_log4om_ping_raises_via_tasklist_when_not_running():
    backend = _make_log4om_backend()
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='')
        with pytest.raises(ConnectionRefusedError):
            backend.ping()


def test_log4om_ping_ok_via_tasklist_future_name():
    # Forward-compat: if exe is renamed to Log4OM.exe in a future version
    backend = _make_log4om_backend()
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='"Log4OM.exe","5678","Console","1","10,000 K"')
        assert backend.ping() == "ok"


def test_log4om_ping_ok_when_tasklist_unavailable():
    # Non-Windows: tasklist not found — assume ok rather than false positive
    backend = _make_log4om_backend()
    with patch('subprocess.run', side_effect=FileNotFoundError):
        assert backend.ping() == "ok"


# ── Log4OM: log listener (M5 worked cache) ───────────────────────────────────

def _log4om_contactinfo_xml(call='W1AW', band='20', mode='FT8',
                             txfreq='1407400', timestamp='20250101 120000'):
    """Build a minimal N1MM contactinfo XML datagram."""
    return (
        f'<contactinfo>'
        f'<call>{call}</call>'
        f'<band>{band}</band>'
        f'<mode>{mode}</mode>'
        f'<txfreq>{txfreq}</txfreq>'
        f'<timestamp>{timestamp}</timestamp>'
        f'</contactinfo>'
    ).encode('utf-8')


def _log4om_run_listener(xml_bytes):
    """
    Start Log4OmBackend log listener with a mocked socket that yields one
    packet then times out.  Returns the list of callback entries received.
    """
    backend = _make_log4om_backend()
    received = []

    recv_calls = [0]

    def fake_recvfrom(bufsize):
        if recv_calls[0] == 0:
            recv_calls[0] += 1
            return xml_bytes, ('127.0.0.1', 12060)
        # Signal stop after first packet
        backend._listener_stop.set()
        raise socket.timeout

    mock_sock = MagicMock()
    mock_sock.recvfrom.side_effect = fake_recvfrom

    with patch('socket.socket', return_value=mock_sock):
        backend.start_log_listener(received.append)
        # Wait for the listener thread to finish (stop event is set inside fake_recvfrom)
        backend._listener_thread.join(timeout=3)

    return received


def test_log4om_listener_callsign_extracted():
    entries = _log4om_run_listener(_log4om_contactinfo_xml(call='W1AW'))
    assert len(entries) == 1
    assert entries[0]['call'] == 'W1AW'


def test_log4om_listener_band_has_m_suffix():
    entries = _log4om_run_listener(_log4om_contactinfo_xml(band='20'))
    assert entries[0]['band'] == '20m'


def test_log4om_listener_mode_preserved():
    entries = _log4om_run_listener(_log4om_contactinfo_xml(mode='FT8'))
    assert entries[0]['mode'] == 'FT8'


def test_log4om_listener_ssb_variants_collapsed():
    for raw_mode in ('USB', 'LSB', 'AM'):
        entries = _log4om_run_listener(_log4om_contactinfo_xml(mode=raw_mode))
        assert entries[0]['mode'] == 'SSB', f"{raw_mode} should collapse to SSB"


def test_log4om_listener_freq_converted_to_mhz():
    # txfreq in tens-of-Hz: 1407400 → 14.074 MHz  (÷100000)
    entries = _log4om_run_listener(_log4om_contactinfo_xml(txfreq='1407400'))
    assert entries[0]['last_freq_mhz'] == '14.074'


def test_log4om_listener_ignores_non_contactinfo():
    # Heartbeat / other UDP packets on same port should be silently dropped
    entries = _log4om_run_listener(b'<SomeOtherMessage><data>x</data></SomeOtherMessage>')
    assert entries == []


def test_log4om_listener_ignores_no_call():
    xml = b'<contactinfo><band>20</band><mode>FT8</mode></contactinfo>'
    entries = _log4om_run_listener(xml)
    assert entries == []


def test_log4om_stop_listener_is_idempotent():
    backend = _make_log4om_backend()
    # stop before ever starting — should not raise
    backend.stop_log_listener()
    backend.stop_log_listener()
