

def test_inxi_always_gets_a_terminal_on_stdin_even_with_no_controlling_tty():
    import os
    import hardware
    fd, to_close = hardware._inxi_stdin()
    try:
        assert fd is not None and os.isatty(fd)
    finally:
        for descriptor in to_close:
            os.close(descriptor)
