"""
Houses the Plotly templates for graphs + coloring options
"""

import plotly.graph_objects as go
import plotly.io as pio

# All colors with "names"
colors_dict = {
    'orange':  '#CF8B40',
    'blue': '#2A547E' ,
    'dark_gray': '#879396',
    'beige':'#F7CAC9',
    'light_blue': '#7095cf',
    'rose': '#A0525A',
    'light_gray': '#D3D3D3',
    'grid': '#E3E6E8',
    'muted_text': '#5B6770',
    'dark_blue_text': '#163855'
}

# Default font for everything. Cambria if installed (comes with Microsoft Office),
# otherwise Georgia, which every Mac and PC has
default_font = "Cambria, Georgia, 'Times New Roman', serif"

# Default text color
default_text_color = colors_dict['dark_blue_text']

# Ordered colors for order of trace coloring. Checked with a color-vision validator:
# every neighboring pair is distinguishable, including for colorblind readers.
# Beige isn't used for data because it's nearly invisible on white (1.4:1 contrast).
default_colorway = [
    colors_dict['blue'],
    colors_dict['orange'],
    colors_dict['light_blue'],
    colors_dict['rose'],
    colors_dict['dark_gray'],
]

# Make a Template object
fed_2025_template = go.layout.Template(

    # The layout property has all the text and styling options for the plot
    layout = dict(

        # Handles the title font
        title = dict(
            font = dict(
                family = default_font,
                size = 36,
                color = default_text_color,
            ),
            xanchor = 'left',
            x=0.05
        ),

        # Handles the legend
        legend = dict(
            # horizontal legend
            orientation='h',
            # set legend to the right
            x=1,
            xanchor='right',
            # set legend above plot
            y=1.05,
            yanchor='bottom',
                font=dict(
                    family=default_font,
                    size=22,
                    color=default_text_color
                ),
            # transparent legened background, plotly bg needs rgba
            bgcolor='rgba(0,0,0,0)',

            # no legened border
            borderwidth=0
        ),

        # Defaults for x-axis styling (ticks)
        xaxis = dict(
            showgrid=True,
            gridwidth=0.5,
            gridcolor=colors_dict['grid'],
            tickfont=dict(
                family=default_font,
                size=18,
                color=default_text_color
            ),
            type='date'  # Set x-axis to date by default
        ),

        # Defaults for the y-axis styling (ticks)
        yaxis = dict(
            showgrid=True,
            gridwidth=0.5,
            gridcolor=colors_dict['grid'],
            tickfont=dict(
                family=default_font,
                size=18,
                color=default_text_color
            )
        ),

        # Defaults for x-axis title styling
        xaxis_title = dict(
            font=dict(
                family=default_font,
                size=24,
                color=default_text_color
            )
        ),

        # Defaults for y-axis title styling
        yaxis_title = dict(
            font=dict(
                family=default_font,
                size=24,
                color=default_text_color
            )
        ),

        # Handles coloring of traces
        colorway = default_colorway,

        width=1200,
        height=500,
    ),

    # The data property stores the defaults for different trace types
    data = dict(

        # For scatter objects (which lines are part of)
        scatter = [
            dict(
                # For line use a default width of 3
                line = dict(
                    width=3
                    ),
                hovertemplate = "%{x|%Y-%m-%d}<br> %{y:.1f}<extra></extra>"
            )
        ]
    )
)
# Register the template
pio.templates['fed_2025'] = fed_2025_template