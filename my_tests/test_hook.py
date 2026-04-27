# ===== TOP COMMENT =====
"""This is a top comment."""

def foo():
    """This is a docstring that should be stripped."""
    # This is a comment that should be stripped
    x = 1  # IMPORTANT: must stay 1
    return x

# ===== BOTTOM COMMENT =====
"""This is a bottom comment."""
