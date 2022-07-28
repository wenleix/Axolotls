# Based on https://github.com/pytorch/torcharrow/blob/ba822da72825150e971c3ee7b6dcb81668eb79f2/torcharrow/dtypes.py
# Chnages may apply

# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import dataclasses
import inspect
import re
import typing as ty
from abc import ABC, abstractmethod
from dataclasses import dataclass, is_dataclass, replace

import numpy as np
import torcharrow._torcharrow
import typing_inspect

# -----------------------------------------------------------------------------
# Aux

# Pretty printing constants; reused everywhere
OPEN = "{"
CLOSE = "}"
NL = "\n"

# Handy Type abbreviations; reused everywhere
ScalarTypes = ty.Union[int, float, bool, str]


# -----------------------------------------------------------------------------
# Schema and Field

MetaData = ty.Dict[str, str]


@dataclass(frozen=True)
class Field:
    name: str
    dtype: "DType"
    metadata: ty.Optional[MetaData] = None

    def __str__(self):
        meta = ""
        if self.metadata is not None:
            meta = (
                f"meta = {OPEN}{', '.join(f'{k}: {v}' for k,v in self.metadata)}{CLOSE}"
            )
        return f"Field('{self.name}', {str(self.dtype)}{meta})"


# -----------------------------------------------------------------------------
# Immutable Types with structural equality...


@dataclass(frozen=True)  # type: ignore
class DType(ABC):
    fields: ty.ClassVar[ty.Any] = NotImplementedError

    typecode: ty.ClassVar[str] = "__TO_BE_DEFINED_IN_SUBCLASS__"
    arraycode: ty.ClassVar[str] = "__TO_BE_DEFINED_IN_SUBCLASS__"

    @property
    @abstractmethod
    def nullable(self):
        return False

    @property
    def py_type(self):
        return type(self.default_value())

    def __str__(self):
        if self.nullable:
            return f"{self.name.title()}(nullable=True)"
        else:
            return self.name

    @abstractmethod
    def constructor(self, nullable):
        pass

    def with_null(self, nullable=True):
        return self.constructor(nullable)

    def default_value(self):
        # must be overridden by all non primitive types!
        return type(self).default

    def __qualstr__(self):
        return "torcharrow.dtypes"


# for now: no float16, and all date and time stuff, no categorical, (and Null is called Void)


@dataclass(frozen=True)
class Void(DType):
    nullable: bool = True
    typecode: ty.ClassVar[str] = "n"
    arraycode: ty.ClassVar[str] = "b"
    name: ty.ClassVar[str] = "void"
    default: ty.ClassVar[ty.Optional[bool]] = None

    def constructor(self, nullable):
        return Void(nullable)


@dataclass(frozen=True)  # type: ignore
class Numeric(DType):
    pass


@dataclass(frozen=True)
class Boolean(DType):
    nullable: bool = False
    typecode: ty.ClassVar[str] = "b"
    arraycode: ty.ClassVar[str] = "b"
    name: ty.ClassVar[str] = "boolean"
    default: ty.ClassVar[bool] = False

    def constructor(self, nullable):
        return Boolean(nullable)


@dataclass(frozen=True)
class Int8(Numeric):
    nullable: bool = False
    typecode: ty.ClassVar[str] = "c"
    arraycode: ty.ClassVar[str] = "b"
    name: ty.ClassVar[str] = "int8"
    default: ty.ClassVar[int] = 0

    def constructor(self, nullable):
        return Int8(nullable)


@dataclass(frozen=True)
class Int16(Numeric):
    nullable: bool = False
    typecode: ty.ClassVar[str] = "s"
    arraycode: ty.ClassVar[str] = "h"
    name: ty.ClassVar[str] = "int16"
    default: ty.ClassVar[int] = 0

    def constructor(self, nullable):
        return Int16(nullable)


@dataclass(frozen=True)
class Int32(Numeric):
    nullable: bool = False
    typecode: ty.ClassVar[str] = "i"
    arraycode: ty.ClassVar[str] = "i"
    name: ty.ClassVar[str] = "int32"
    default: ty.ClassVar[int] = 0

    def constructor(self, nullable):
        return Int32(nullable)


@dataclass(frozen=True)
class Int64(Numeric):
    nullable: bool = False
    typecode: ty.ClassVar[str] = "l"
    arraycode: ty.ClassVar[str] = "l"
    name: ty.ClassVar[str] = "int64"
    default: ty.ClassVar[int] = 0

    def constructor(self, nullable):
        return Int64(nullable)


# Not all Arrow types are supported. We don't have a backend to support unsigned
# integer types right now so they are removed to not confuse users. Feel free to
# add unsigned int types when we have a supporting backend.


@dataclass(frozen=True)
class Float32(Numeric):
    nullable: bool = False
    typecode: ty.ClassVar[str] = "f"
    arraycode: ty.ClassVar[str] = "f"
    name: ty.ClassVar[str] = "float32"
    default: ty.ClassVar[float] = 0.0

    def constructor(self, nullable):
        return Float32(nullable)


@dataclass(frozen=True)
class Float64(Numeric):
    nullable: bool = False
    typecode: ty.ClassVar[str] = "g"
    arraycode: ty.ClassVar[str] = "d"
    name: ty.ClassVar[str] = "float64"
    default: ty.ClassVar[float] = 0.0

    def constructor(self, nullable):
        return Float64(nullable)


@dataclass(frozen=True)
class String(DType):
    nullable: bool = False
    typecode: ty.ClassVar[str] = "u"  # utf8 string (n byte)
    arraycode: ty.ClassVar[str] = "w"  # wchar_t (2 byte)
    name: ty.ClassVar[str] = "string"
    default: ty.ClassVar[str] = ""

    def constructor(self, nullable):
        return String(nullable)


@dataclass(frozen=True)
class Map(DType):
    key_dtype: DType
    item_dtype: DType
    nullable: bool = False
    keys_sorted: bool = False
    name: ty.ClassVar[str] = "Map"
    typecode: ty.ClassVar[str] = "+m"
    arraycode: ty.ClassVar[str] = ""

    @property
    def py_type(self):
        return ty.Dict[self.key_dtype.py_type, self.item_dtype.py_type]

    def constructor(self, nullable):
        return Map(self.key_dtype, self.item_dtype, nullable)

    def __str__(self):
        nullable = ", nullable=" + str(self.nullable) if self.nullable else ""
        return f"Map({self.key_dtype}, {self.item_dtype}{nullable})"

    def default_value(self):
        return {}


@dataclass(frozen=True)
class List(DType):
    item_dtype: DType
    nullable: bool = False
    fixed_size: int = -1
    name: ty.ClassVar[str] = "List"
    typecode: ty.ClassVar[str] = "+l"
    arraycode: ty.ClassVar[str] = ""

    @property
    def py_type(self):
        return ty.List[self.item_dtype.py_type]

    def constructor(self, nullable, fixed_size=-1):
        return List(self.item_dtype, nullable, fixed_size)

    def __str__(self):
        nullable = ", nullable=" + str(self.nullable) if self.nullable else ""
        fixed_size = (
            ", fixed_size=" + str(self.fixed_size) if self.fixed_size >= 0 else ""
        )
        return f"List({self.item_dtype}{nullable}{fixed_size})"

    def default_value(self):
        return []


@dataclass(frozen=True)
class Struct(DType):
    fields: ty.List[Field]
    nullable: bool = False
    is_dataframe: bool = False
    metadata: ty.Optional[MetaData] = None
    name: ty.ClassVar[str] = "Struct"
    typecode: ty.ClassVar[str] = "+s"
    arraycode: ty.ClassVar[str] = ""

    # For generating NamedTuple class name for cached _py_type (done in __post__init__)
    _global_py_type_id: ty.ClassVar[int] = 0
    _local_py_type_id: int = dataclasses.field(compare=False, default=-1)

    # TODO: perhaps this should be a private method
    def get_index(self, name: str) -> int:
        for idx, field in enumerate(self.fields):
            if field.name == name:
                return idx
        # pyre-fixme[7]: Expected `int` but got `None`.
        return None

    def __getstate__(self):
        # _py_type is NamedTuple which is not pickle-able, skip it
        return (self.fields, self.nullable, self.is_dataframe, self.metadata)

    def __setstate__(self, state):
        # Restore state, __setattr__ hack is needed due to the frozen dataclass
        object.__setattr__(self, "fields", state[0])
        object.__setattr__(self, "nullable", state[1])
        object.__setattr__(self, "is_dataframe", state[2])
        object.__setattr__(self, "metadata", state[3])

        # reconstruct _py_type
        self.__post_init__()

    def __post_init__(self):
        if self.nullable:
            for f in self.fields:
                if not f.dtype.nullable:
                    raise TypeError(
                        f"nullable structs require each field (like {f.name}) to be nullable as well."
                    )
        object.__setattr__(self, "_local_py_type_id", type(self)._global_py_type_id)
        type(self)._global_py_type_id += 1

    def _set_py_type(self):
        # cache the type instance, __setattr__ hack is needed due to the frozen dataclass
        # the _py_type is not listed above to avoid participation in equality check

        def fix_name(name, idx):
            # Anonomous Row
            if name == "":
                return "f_" + str(idx)

            # Remove invalid character for NamedTuple
            # TODO: this might cause name duplicates, do disambiguation
            name = re.sub("[^a-zA-Z0-9_]", "_", name)
            if name == "" or name[0].isdigit() or name[0] == "_":
                name = "f_" + name
            return name

        object.__setattr__(
            self,
            "_py_type",
            ty.NamedTuple(
                "TorchArrowGeneratedStruct_" + str(self._local_py_type_id),
                [
                    (fix_name(f.name, idx), f.dtype.py_type)
                    for (idx, f) in enumerate(self.fields)
                ],
            ),
        )

    @property
    def py_type(self):
        if not hasattr(self, "_py_type"):
            # this call is expensive due to the namedtuple creation, so
            # do it lazily
            self._set_py_type()
        return self._py_type

    def constructor(self, nullable):
        return Struct(self.fields, nullable)

    def get(self, name):
        for f in self.fields:
            if f.name == name:
                return f.dtype
        raise KeyError(f"{name} not among fields")

    def __str__(self):
        nullable = ", nullable=" + str(self.nullable) if self.nullable else ""
        fields = f"[{', '.join(str(f) for f in self.fields)}]"
        meta = ""
        if self.metadata is not None:
            meta = f", meta = {OPEN}{', '.join(f'{k}: {v}' for k,v in self.metadata)}{CLOSE}"
        else:
            return f"Struct({fields}{nullable}{meta})"

    def default_value(self):
        return tuple(f.dtype.default_value() for f in self.fields)


# only used internally for type inference -------------------------------------


@dataclass(frozen=True)
class Tuple(DType):
    fields: ty.List[DType]
    nullable: bool = False
    is_dataframe: bool = False
    metadata: ty.Optional[MetaData] = None
    name: ty.ClassVar[str] = "Tuple"
    typecode: ty.ClassVar[str] = "+t"
    arraycode: ty.ClassVar[str] = ""

    @property
    def py_type(self):
        return tuple

    def constructor(self, nullable):
        return Tuple(self.fields, nullable)

    def default_value(self):
        return tuple(f.dtype.default_value() for f in self.fields)


@dataclass(frozen=True)
class Any(DType):
    nullable: bool = True
    typecode: ty.ClassVar[str] = "?"
    arraycode: ty.ClassVar[str] = "?"
    name: ty.ClassVar[str] = "any"
    default: ty.ClassVar[ty.Optional[bool]] = None

    @property
    def size(self):
        # currently 1 byte per bit
        raise ValueError("Shouldn't be called")

    @property
    def py_type(self):
        raise ValueError("Shouldn't be called")

    def constructor(self, nullable=True):
        assert nullable
        return Any()


# TorchArrow does not yet support these types ---------------------------------
Tag = str

# abstract


@dataclass(frozen=True)  # type: ignore
class Union_(DType):
    pass


@dataclass(frozen=True)  # type: ignore
class DenseUnion(DType):
    tags: ty.List[Tag]
    name: ty.ClassVar[str] = "DenseUnion"
    typecode: ty.ClassVar[str] = "+ud"
    arraycode: ty.ClassVar[str] = ""


@dataclass(frozen=True)  # type: ignore
class SparseUnion(DType):
    tags: ty.List[Tag]
    name: ty.ClassVar[str] = "SparseUnion"
    typecode: ty.ClassVar[str] = "+us"
    arraycode: ty.ClassVar[str] = ""


boolean = Boolean()
int8 = Int8()
int16 = Int16()
int32 = Int32()
int64 = Int64()
float32 = Float32()
float64 = Float64()
string = String()

# Type test -------------------------------------------------------------------
# can be deleted once TorchArrow is implemented over velox...


def is_void(t):
    """
    Return True if value is an instance of a void type.
    """
    # print('is_boolean', t.typecode)
    return t.typecode == "n"


def is_boolean(t):
    """
    Return True if value is an instance of a boolean type.
    """
    # print('is_boolean', t.typecode)
    return t.typecode == "b"


def is_boolean_or_numerical(t):
    return is_boolean(t) or is_numerical(t)


def is_numerical(t):
    return is_integer(t) or is_floating(t)


def is_integer(t):
    """
    Return True if value is an instance of any integer type.
    """
    return t.typecode in "csilCSIL"


def is_signed_integer(t):
    """
    Return True if value is an instance of any signed integer type.
    """
    return t.typecode in "csil"


def is_int8(t):
    """
    Return True if value is an instance of an int8 type.
    """
    return t.typecode == "c"


def is_int16(t):
    """
    Return True if value is an instance of an int16 type.
    """
    return t.typecode == "s"


def is_int32(t):
    """
    Return True if value is an instance of an int32 type.
    """
    return t.typecode == "i"


def is_int64(t):
    """
    Return True if value is an instance of an int64 type.
    """
    return t.typecode == "l"


def is_floating(t):
    """
    Return True if value is an instance of a floating point numeric type.
    """
    return t.typecode in "fg"


def is_float32(t):
    """
    Return True if value is an instance of a float32 (single precision) type.
    """
    return t.typecode == "f"


def is_string(t):
    return t.typecode == "u"


def is_float64(t):
    """
    Return True if value is an instance of a float32 (single precision) type.
    """
    return t.typecode == "g"


def is_list(t):
    return t.typecode.startswith("+l")


def is_map(t):
    return t.typecode.startswith("+m")


def is_struct(t):
    return t.typecode.startswith("+s")


def is_primitive(t):
    return t.typecode[0] != "+"


def is_tuple(t):
    return t.typecode.startswith("+t")


def contains_tuple(t: DType):
    if is_tuple(t):
        return True
    if is_list(t):
        # pyre-fixme[16]: `DType` has no attribute `item_dtype`.
        return contains_tuple(t.item_dtype)
    if is_map(t):
        # pyre-fixme[16]: `DType` has no attribute `key_dtype`.
        return contains_tuple(t.key_dtype) or contains_tuple(t.item_dtype)
    if is_struct(t):
        return any(contains_tuple(f.dtype) for f in t.fields)

    return False


def is_any(t):
    return t.typecode == "?"


# Infer types from values -----------------------------------------------------
PREFIX_LENGTH = 5


def prt(value, type):
    # print("<", value, ":", type, ">")
    return type


def infer_dtype_from_value(value):
    if value is None:
        return Void()
    if isinstance(value, (bool, np.bool8)):
        return prt(value, boolean)
    if isinstance(value, (np.int8)):
        return prt(value, int8)
    if isinstance(value, (np.int16)):
        return prt(value, int16)
    if isinstance(value, (np.int32)):
        return prt(value, int32)
    if isinstance(value, (int, np.integer)):
        return prt(value, int64)
    if isinstance(value, np.float64):
        # please make sure this `if` check precedes the below one, since
        # the `np.float64` is also the instance of `float`
        return prt(value, float64)
    if isinstance(value, (float, np.float32)):
        return prt(value, float32)
    if isinstance(value, (str, np.str_)):
        return prt(value, string)
    if isinstance(value, list):
        dtype = infer_dtype_from_prefix(value[:PREFIX_LENGTH])
        return prt(value, List(dtype))
    if isinstance(value, dict):
        key_dtype = infer_dtype_from_prefix(list(value.keys())[:PREFIX_LENGTH])
        items_dtype = infer_dtype_from_prefix(list(value.values())[:PREFIX_LENGTH])
        return prt(value, Map(key_dtype, items_dtype))
    if isinstance(value, tuple):
        dtypes = []
        for t in value:
            dtypes.append(infer_dtype_from_value(t))
        return prt(value, Tuple(dtypes))
    raise AssertionError(f"unexpected case {value} of type {type(value)}")


def infer_dtype_from_prefix(prefix: ty.Sequence) -> ty.Optional[DType]:
    if len(prefix) == 0:
        return Any()
    dtype = infer_dtype_from_value(prefix[0])
    for p in prefix[1:]:
        old_dtype = dtype
        next_dtype = infer_dtype_from_value(p)
        dtype = common_dtype(old_dtype, next_dtype)
        if dtype is None:
            raise ValueError(
                f"Cannot infer type of {prefix}: {old_dtype} {old_dtype.typecode}, {next_dtype} {next_dtype.typecode} {dtype}"
            )
    return dtype


def infer_dype_from_callable_hint(
    func: ty.Callable,
    # pyre-fixme[31]: Expression `Type])` is not a valid type.
) -> (ty.Optional[DType], ty.Optional[ty.Type]):
    dtype = None
    py_type = None
    if (
        inspect.isfunction(func)
        or inspect.ismethod(func)
        or inspect.isclass(func)
        or inspect.ismodule(func)
    ):
        # get_type_hints expects module, class, method, or function as input
        signature = ty.get_type_hints(func)
    else:
        signature = ty.get_type_hints(func.__call__)

    if "return" in signature and signature["return"] is not None:
        py_type = signature["return"]
        dtype = dtype_of_type(py_type)

    return (dtype, py_type)


# lub of two types for inference ----------------------------------------------


_promotion_list = [
    ("b", "b", boolean),
    ("bc", "bc", int8),
    ("bcs", "bcs", int16),
    ("bcsi", "bcsi", int32),
    ("bcsil", "bcsil", int64),
    ("bcsilf", "bcsilf", float32),
    ("bcsilfg", "bcsilfg", float64),
]


def promote(l, r):
    assert is_boolean_or_numerical(l) and is_boolean_or_numerical(r)

    lt = l.typecode
    rt = r.typecode
    if lt == rt:
        return l.with_null(l.nullable or r.nullable)

    for lts, rts, dtype in _promotion_list:
        if (lt in lts) and (rt in rts):
            return dtype.with_null(l.nullable or r.nullable)
    return None


def common_dtype(l: DType, r: DType) -> ty.Optional[DType]:
    if is_void(l):
        return r.with_null()
    if is_void(r):
        return l.with_null()
    if is_any(l):
        return r
    if is_any(r):
        return l

    if is_string(l) and is_string(r):
        return String(l.nullable or r.nullable)
    if is_boolean_or_numerical(l) and is_boolean_or_numerical(r):
        return promote(l, r)
    if is_tuple(l) and is_tuple(r) and len(l.fields) == len(r.fields):
        res = []
        for i, j in zip(l.fields, r.fields):
            m = common_dtype(i, j)
            if m is None:
                return None
            res.append(m)
        return Tuple(res).with_null(l.nullable or r.nullable)
    if is_map(l) and is_map(r):
        # pyre-fixme[16]: `DType` has no attribute `key_dtype`.
        k = common_dtype(l.key_dtype, r.key_dtype)
        # pyre-fixme[16]: `DType` has no attribute `item_dtype`.
        i = common_dtype(l.item_dtype, r.item_dtype)
        return (
            Map(k, i).with_null(l.nullable or r.nullable)
            if k is not None and i is not None
            else None
        )
    if is_list(l) and is_list(r):
        k = common_dtype(l.item_dtype, r.item_dtype)
        return List(k).with_null(l.nullable or r.nullable) if k is not None else None
    if l.with_null() == r.with_null():
        return l if l.nullable else r
    return None


# # Derive result types from operators ------------------------------------------
# Currently not used since we use numpy 's promotion rules...

# # DESIGN BUG: TODO needs actually both sides for symmetric promotion rules ...
# _arithmetic_ops = ["add", "sub", "mul", "floordiv", "truediv", "mod", "pow"]
# _comparison_ops = ["eq", "ne", "lt", "gt", "le", "ge"]
# _logical_ops = ["and", "or"]


# def derive_dtype(left_dtype, op):
#     if is_numerical(left_dtype) and op in _arithmetic_ops:
#         if op == "truediv":
#             return Float64(left_dtype.nullable)
#         elif op == "floordiv":
#             if is_integer(left_dtype):
#                 return Int64(left_dtype.nullable)
#             else:
#                 return Float64(left_dtype.nullable)
#         else:
#             return left_dtype
#     if is_boolean(left_dtype) and op in _logical_ops:
#         return left_dtype
#     if op in _comparison_ops:
#         return Boolean(left_dtype.nullable)
#     raise AssertionError(
#         f"derive_dtype, unexpected type {left_dtype} for operation {op}"
#     )


# def derive_operator(op):
#     return _operator_map[op]


# def _or(a, b):
#     return a or b


# def _and(a, b):
#     return a and b


# _operator_map = {
#     "add": operator.add,
#     "sub": operator.sub,
#     "mul": operator.mul,
#     "eq": operator.eq,
#     "ne": operator.ne,
#     "or": _or,  # logical instead of bitwise
#     "and": _and,  # logical instead of bitwise
#     "floordiv": operator.floordiv,
#     "truediv": operator.truediv,
#     "mod": operator.mod,
#     "pow": operator.pow,
#     "lt": operator.lt,
#     "gt": operator.gt,
#     "le": operator.le,
#     "ge": operator.ge,
# }


def get_agg_op(op: str, dtype: DType) -> ty.Tuple[ty.Callable, DType]:
    if op not in _agg_ops:
        raise ValueError(f"undefined aggregation operator ({op})")
    if op in ["min", "max", "sum", "prod", "mode"]:
        return (_agg_ops[op], dtype)
    if op in ["mean", "median"]:
        return (_agg_ops[op], Float64(dtype.nullable))
    if op in ["count"]:
        return (_agg_ops[op], Int64(dtype.nullable))
    raise AssertionError("unexpected case")


_agg_ops = {
    "min": lambda c: c.min(),
    "max": lambda c: c.max(),
    "all": lambda c: c.all(),
    "any": lambda c: c.any(),
    "sum": lambda c: c.sum(),
    "prod": lambda c: c.prod(),
    "mean": lambda c: c.mean(),
    "median": lambda c: c.median(),
    "mode": lambda c: c.mode(),
    "count": lambda c: c._count(),
}


def np_typeof_dtype(t: DType):  # -> np.dtype[]:
    if is_boolean(t):
        return np.bool8
    if is_int8(t):
        return np.int8
    if is_int16(t):
        return np.int16
    if is_int32(t):
        return np.int32
    if is_int64(t):
        return np.int64
    if is_float32(t):
        return np.float32
    if is_float64(t):
        return np.float64
    if is_string(t):
        # we translate strings not into np.str_ but into object
        return object

    raise AssertionError(
        f"translation of dtype {type(t).__name__} to numpy type unsupported"
    )


def typeof_np_ndarray(t: np.ndarray) -> DType:
    return typeof_np_dtype(t.dtype)


def typeof_np_dtype(t: np.dtype) -> DType:
    # only suppport the following non-structured columns,...
    if t == np.bool8:
        return boolean
    if t == np.int8:
        return int8
    if t == np.int16:
        return int16
    if t == np.int32:
        return int32
    if t == np.int64:
        return int64
    # any float array can have nan -- all nan(s) will be masked
    # -> so result type is FloatXX(True)
    if t == np.float32:
        return Float32(nullable=True)
    if t == np.float64:
        return Float64(nullable=True)
    # can't test nicely for strings so we use the kind test
    if t.kind == "U":  # unicode like
        return string
    # any object array can have non-strings: all non strings will be masked.
    # -> so result type is String(True)
    if t == object:
        return String(nullable=True)

    raise AssertionError(
        f"translation of numpy type {type(t).__name__} to dtype unsupported"
    )


def cast_as(dtype):
    if is_string(dtype):
        return str
    if is_integer(dtype):
        return int
    if is_boolean(dtype):
        return bool
    if is_floating(dtype):
        return float
    raise AssertionError(f"cast to {dtype} unsupported")


def get_underlying_dtype(dtype: DType) -> DType:
    return replace(dtype, nullable=False)


def get_nullable_dtype(dtype: DType) -> DType:
    return replace(dtype, nullable=True)


# Based on https://github.com/pytorch/pytorch/blob/c48e6f014a0cca0adc18e1a39a8fd724fe7ab83a/torch/_jit_internal.py#L1113-L1118
def get_origin(target_type):
    return getattr(target_type, "__origin__", None)


def get_args(target_type):
    return getattr(target_type, "__args__", None)


def dtype_of_type(typ: ty.Union[ty.Type, DType]) -> DType:
    assert typ is not None

    if isinstance(typ, DType):
        return typ

    if typing_inspect.is_tuple_type(typ):
        return Tuple([dtype_of_type(a) for a in typing_inspect.get_args(typ)])
    if inspect.isclass(typ) and issubclass(typ, tuple) and hasattr(typ, "_fields"):
        fields = typ._fields
        field_types = getattr(typ, "__annotations__", None)
        if field_types is None or any(n not in field_types for n in fields):
            raise TypeError(
                f"Can't infer type from namedtuple without type hints: {typ}"
            )
        return Struct([Field(n, dtype_of_type(field_types[n])) for n in fields])
    if is_dataclass(typ):
        return Struct(
            [Field(f.name, dtype_of_type(f.type)) for f in dataclasses.fields(typ)]
        )
    if get_origin(typ) in (List, list):
        args = get_args(typ)
        assert len(args) == 1
        elem_type = dtype_of_type(args[0])
        return List(elem_type)
    if get_origin(typ) in (ty.Dict, dict):
        args = get_args(typ)
        assert len(args) == 2
        key = dtype_of_type(args[0])
        value = dtype_of_type(args[1])
        return Map(key, value)
    if typing_inspect.is_optional_type(typ):
        args = get_args(typ)
        assert len(args) == 2
        if issubclass(args[1], type(None)):
            contained = args[0]
        else:
            contained = args[1]
        return dtype_of_type(contained).with_null()
    # same inference rules as for values above
    if typ is float:
        # PyTorch defaults to use Single-precision floating-point format (float32) for Python float type
        return float32
    if typ is int:
        return int64
    if typ is str:
        return string
    if typ is bool:
        return boolean
    raise TypeError(f"Can't infer dtype from {typ}")


def dtype_from_batch_pytype(typ: ty.Type) -> DType:
    """
    Like dtype_of_type but representing type hint for the set of rows. Can be a Column or a python List of nested types
    """
    from .icolumn import Column

    assert type is not None

    if inspect.isclass(typ) and issubclass(typ, Column):
        # TODO: we need a type annotation for Columns with statically accessible dtype
        raise TypeError("Cannot infer dtype from Column")

    if get_origin(typ) in (List, list):
        args = get_args(typ)
        assert len(args) == 1
        return dtype_of_type(args[0])

    raise TypeError("The outer type annotation must be a list or a Column")
