<?php

declare(strict_types=1);

namespace LombokSerde;

enum SerdeErrorCode: string
{
    case SyntaxError = 'SyntaxError';
    case UnexpectedEof = 'UnexpectedEof';
    case TypeMismatch = 'TypeMismatch';
    case MissingField = 'MissingField';
    case UnknownField = 'UnknownField';
    case OutOfRange = 'OutOfRange';
    case DepthExceeded = 'DepthExceeded';
    case InvalidUnicode = 'InvalidUnicode';
    case DuplicateKey = 'DuplicateKey';
    case Unsupported = 'Unsupported';
    case Custom = 'Custom';
}
