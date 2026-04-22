"""参考基础模型封装。"""

from .victim_model import GenerativeAuditModel


class ReferenceModel(GenerativeAuditModel):
    """与受害模型共享接口，但通常不做微调。"""

    def __init__(self, model_name="gpt2", device=None, max_length=256, lazy_load=True):
        super().__init__(model_name=model_name, device=device, max_length=max_length, lazy_load=lazy_load)
