from .column_base import ColumnBase
from . import dtypes as dt
from typing import Optional
import torch

class NumericColumn(ColumnBase):
    def __init__(self, values: torch.Tensor, presence: Optional[torch.BoolTensor] = None) -> None:
        super().__init__(dtype=dt._dtype_from_pytorch_dtype(dtype=values.dtype, nullable=presence is not None))

        if not isinstance(values, torch.Tensor) or values.dim() != 1:
            raise ValueError("NumericCollumn expects 1D values Tensor")
        if presence is not None and (values.shape != presence.shape):
            raise ValueError(f"Mismatched shape for values({values.shape}) and presence({presence.shape})")

        self._values = values
        self._presence = presence

    def clone(self) -> "NumericColumn":
        return NumericColumn(
            values=self.values.detach().clone(),
            presence=self.presence.detach().clone() if self.presence is not None else None
        )

    def __getitem__(self, key):
        if isinstance(key, int):
            if self.presence is None or self.presence[key]:
                return self.values[key].item()
            return None

        if isinstance(key, slice):
            values = self.values[key]
            presence = self.presence[key] if self.presence is not None else None
            return NumericColumn(values=values, presence=presence)

        raise ValueError(f"Unsupported key for __getitem__: f{key}")

    def __str__(self) -> str:
        return f"""NumericColumn(
    values={self.values},
    presence={self.presence},
    dtype={self.dtype},
)"""

    @property
    def values(self) -> torch.Tensor:
        return self._values

    @property
    def presence(self) -> Optional[torch.BoolTensor]:
        return self._presence

    def __len__(self) -> int:
        return len(self._values)

    # Data cleaning ops
    def fill_null(self, val):
        if self.presence is None:
            # TODO: should we return a copy here?
            return self

        values = self.values.clone()
        values[~self.presence] = val
        return NumericColumn(values=values)

    def fill_null_(self, val):
        if self.presence is None:
            return self
        
        self.values[~self.presence] = val
        self._presence = None
        self._dtype = self._dtype.with_null(nullable=False)

        return self

    # Common Arithmatic / PyTorch ops
    def __add__(self, other):
        if isinstance(other, NumericColumn):
            return NumericColumn(
                self.values + other.values,
                presence=NumericColumn._presence_for_binary_op(self.presence, other.presence)
            )

        if isinstance(other, (float, int, torch.Tensor)):
            return NumericColumn(self.values + other, presence=self.presence)

        raise ValueError(f"Unsupported value {other}")

    def __radd__(self, other):
        if isinstance(other, (float, int, torch.Tensor)):
            return NumericColumn(other + self.values, presence=self.presence)

        raise ValueError(f"Unsupported value {other}")

    def __truediv__(self, other):
        if isinstance(other, NumericColumn):
            return NumericColumn(
                self.values / other.values,
                presence=NumericColumn._presence_for_binary_op(self.presence, other.presence)
            )

        if isinstance(other, (float, int, torch.Tensor)):
            return NumericColumn(self.values / other, presence=self.presence)

        raise ValueError(f"Unsupported value {other}")

    def __rtruediv__(self, other):
        if isinstance(other, (float, int, torch.Tensor)):
            return NumericColumn(other / self.values, presence=self.presence)

        raise ValueError(f"Unsupported value {other}")

    def log(self) -> "NumericColumn":
        return NumericColumn(
            values=self.values.log(),
            presence=self.presence,
        )

    def logit(self, eps=None) -> "NumericColumn":
        if eps is None or isinstance(eps, (float, int, torch.Tensor)):
            return NumericColumn(
                values=self.values.logit(eps),
                presence=self.presence,
            )

        raise ValueError(f"Unsupported value {eps}")

    @property
    def values(self) -> torch.Tensor:
        return self._values
    
    @property
    def presence(self) -> Optional[torch.BoolTensor]:
        return self._presence

    def __len__(self) -> int:
        return self._values.numel()

    def to_arrow(self):
        # TODO: Check whether PyArrow is available 
        import pyarrow as pa
        from .utils import _get_arrow_buffer_from_tensor

        if not self.presence is not None and self.values.dtype != torch.bool:
            # Wrap Tensor memory into Arrow buffer, this avoids dependency on NumPy
            values_buffer = _get_arrow_buffer_from_tensor(self.values)

            return pa.Array.from_buffers(
                type=dt._dtype_to_arrow_type(self.values.dtype),
                length=self.values.numel(),
                buffers=[None, values_buffer],  # validity buffer is None
            )

        # Arrow's validity buffer is a compressed bitmap,
        # while Axolotls's presence tensor will use 1 byte for each bool
        # For now go through NumPy, we can do the bitmap compression to avoid dependency on NumPy
        values = self.values.numpy()
        mask = ~self.presence.numpy() if self.presence is not None else None

        return pa.array(values, mask=mask)

    @staticmethod
    def _presence_for_binary_op(
        presence1: Optional[torch.BoolTensor],
        presence2: Optional[torch.BoolTensor]
    ) -> Optional[torch.BoolTensor]:
        if presence1 is not None and presence2 is not None:
            return presence1 & presence2
        return presence1 or presence2
