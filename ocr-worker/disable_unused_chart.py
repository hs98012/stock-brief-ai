"""Version-bound fix for PaddleX 3.3.13's unconditional disabled-chart load.

Upstream layout_parsing/pipeline_v2.py initializes ChartRecognition even when
use_chart_recognition=False. Honor that flag without changing OCR/table models.
Fail the image build if upstream code changes; never silently patch other code.
"""
from importlib.metadata import version
from pathlib import Path
import sysconfig

assert version('paddlex') == '3.3.13'
path=Path(sysconfig.get_paths()['purelib'])/'paddlex/inference/pipelines/layout_parsing/pipeline_v2.py'
old='''        self.chart_recognition_model = self.create_model(
            chart_recognition_config,
        )'''
new='''        self.chart_recognition_model = None
        if self.use_chart_recognition:
            self.chart_recognition_model = self.create_model(chart_recognition_config)'''
source=path.read_text()
assert source.count(old)==1, 'Unexpected PaddleX chart initialization'
path.write_text(source.replace(old,new))
