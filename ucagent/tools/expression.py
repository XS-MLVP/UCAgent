import re
from enum import Enum
from typing import Optional
from dataclasses import dataclass


class TokenType(Enum):
    """Enumeration of token types in the expression language."""
    SPACE = "space"  # White space
    VAL = "val"      # Constant numeric value
    OP = "op"        # Operator
    PARL = "parl"    # Left parenthesis '('
    PARR = "parr"    # Right parenthesis ')'
    INVALID = "invalid"  # Invalid/unknown token


@dataclass
class Token:
    """
    Represents a token in the expression.
    
    Attributes:
        type: The type of token (TokenType enum)
        value: For VAL tokens, the integer value of the constant
        op_str: For OP tokens, the string representation of the operator
        prec: For OP tokens, the precedence level (higher = binds tighter)
    """
    type: TokenType
    value: int = 0 # for VAL tokens
    op_str: str = "" # for OP tokens
    prec: int = 0  # for OP tokens (precedence)


@dataclass
class TokenizationRule:
    """
    Defines a rule for tokenizing input strings.
    
    Attributes:
        pattren: Regular expression pattern to match the token
        token_type: Type of token to create when pattern matches
        precedence: Operator precedence (for OP tokens, 0 for others)
        radix: Numeric base for parsing VAL tokens (2, 8, 10, 16)
    """
    pattren: re.Pattern
    token_type: TokenType
    precedence: int
    radix: int


# Maximum operator precedence value (used for unary operators)
MAX_PREC = 8

# Tokenization rules in order of priority (first match wins)
# Format: (pattern, token_type, precedence, radix)
TOKENIZATION_RULES = [
    TokenizationRule(re.compile(r"\s+"), TokenType.SPACE, 0, 0),
    TokenizationRule(re.compile(r"0b[01]+"), TokenType.VAL, 0, 2),
    TokenizationRule(re.compile(r"0o[0-7]+"), TokenType.VAL, 0, 8),
    TokenizationRule(re.compile(r"0x[0-9a-fA-F]+"), TokenType.VAL, 0, 16),
    TokenizationRule(re.compile(r"[0-9]+"), TokenType.VAL, 0, 10),
    TokenizationRule(re.compile(r"<<|>>"), TokenType.OP, 5, 0),
    TokenizationRule(re.compile(r">=|<=|>|<|==|!="), TokenType.OP, 4, 0),
    TokenizationRule(re.compile(r"[*/%]"), TokenType.OP, 7, 0),
    TokenizationRule(re.compile(r"[+-]"), TokenType.OP, 6, 0),
    TokenizationRule(re.compile(r"&"), TokenType.OP, 3, 0),
    TokenizationRule(re.compile(r"\^"), TokenType.OP, 2, 0),
    TokenizationRule(re.compile(r"\|"), TokenType.OP, 1, 0),
    TokenizationRule(re.compile(r"[~!]"), TokenType.OP, MAX_PREC, 0),
    TokenizationRule(re.compile(r"\("), TokenType.PARL, 0, 0),
    TokenizationRule(re.compile(r"\)"), TokenType.PARR, 0, 0),
]


def tokenize_expression(expr: str) -> list[Token]:
    """
    Tokenize an input expression string into a list of tokens.
    
    This function scans the input string from left to right, matching against
    the tokenization rules in order. It handles numeric literals in different
    bases and converts them to integer values.
    
    Args:
        expr: The expression string to tokenize
        
    Returns:
        List of Token objects. May include TokenType.INVALID if syntax error.
        TokenType.SPACE tokens are included but should be filtered out before parsing.
    """

    tokens = []
    
    while expr:
        matched = False
        for rule in TOKENIZATION_RULES:
            match = rule.pattren.match(expr)
            if match is not None:
                matched = True
                token_str = match.group(0)
                
                if rule.token_type == TokenType.VAL:
                    # Parse numeric value
                    if rule.radix != 10:
                        # Remove prefix
                        value = int(token_str[2:], rule.radix)
                    else:
                        value = int(token_str, rule.radix)
                    tokens.append(Token(type=rule.token_type, value=value))    
                elif rule.token_type == TokenType.OP:
                    tokens.append(Token(type=rule.token_type, op_str=token_str, prec=rule.precedence))       
                elif rule.token_type==TokenType.PARL or rule.token_type==TokenType.PARR:  # PARL or PARR
                    tokens.append(Token(type=rule.token_type))
                
                expr = expr[len(token_str):]
                break
        
        if not matched:
            tokens.append(Token(type=TokenType.INVALID))
            break
    
    return tokens


def parse_expression(tokens: list[Token]) -> Optional[list[Token]]:
    """
    Parse tokenized expression into postfix notation (Reverse Polish Notation).
    
    This function implements a recursive descent parser that converts infix
    expressions to postfix notation using the Shunting Yard algorithm logic.
    It handles operator precedence, parentheses, and unary operators.
    
    Args:
        tokens: List of Token objects (should not contain TokenType.SPACE)
        
    Returns:
        List of Token objects in postfix order, or None if parsing fails.
        The output is suitable for evaluation by evaluate_postfix_expression().
    """
    
    def is_numerical(token: Token) -> bool:
        return token.type == TokenType.VAL
    
    def likely_unary(token: Token) -> bool:
        if token.type != TokenType.OP:
            return False
        if token.prec == MAX_PREC:
            return True
        if token.op_str in ("+", "-"):
            return True
        return False
    
    # Trivial cases
    if not tokens:
        return None
    if len(tokens) == 1:
        if is_numerical(tokens[0]):
            return tokens
        else:
            return None
    
    # Find the last binary operator with lowest precedence
    for prec in range(1, MAX_PREC):
        par_cnt = 0
        op_index = 0
        
        for i, token in enumerate(tokens):
            if token.type == TokenType.PARL:
                par_cnt += 1
            elif token.type == TokenType.PARR:
                par_cnt -= 1
            
            if par_cnt < 0:
                return None
            elif (par_cnt == 0 and  # Not inside parentheses
                  token.type == TokenType.OP and 
                  token.prec == prec and  # Operator of specified precedence
                  i > 0 and 
                  (is_numerical(tokens[i-1]) or tokens[i-1].type == TokenType.PARR)):
                op_index = i
        
        if par_cnt != 0:
            return None
        elif op_index != 0:
            left = parse_expression(tokens[:op_index])
            right = parse_expression(tokens[op_index + 1:])
            if left is not None and right is not None:
                result = left + right + [tokens[op_index]]
                return result
            return None
    
    # Remove outer parentheses
    if (len(tokens) >= 3 and 
        tokens[0].type == TokenType.PARL and 
        tokens[-1].type == TokenType.PARR):
        return parse_expression(tokens[1:-1])
    
    # Handle unary operator at beginning
    if likely_unary(tokens[0]):
        rest = parse_expression(tokens[1:])
        if rest is not None:
            rest.append(tokens[0])
            # Mark as unary by setting precedence to MAX_PREC
            rest[-1].prec = MAX_PREC
            return rest
        return None
    
    return None


def evaluate_postfix_expression(postfix_expr: list[Token]) -> Optional[int]:
    """
    Evaluate postfix expression (Reverse Polish Notation).
    
    This function evaluates expressions in postfix notation using a stack.
    It implements C-style integer arithmetic semantics, including:
    - Division truncates toward zero (not floor division)
    - Remainder sign matches dividend (C-style %)
    - Bitwise operations on two's complement integers
    
    Args:
        postfix_expr: List of Token objects in postfix order
        
    Returns:
        Integer result of evaluation, or None if evaluation fails
        (e.g., division by zero, invalid expression, stack underflow)
    """

    stack: list[int] = []
    
    for token in postfix_expr:
        if token.type == TokenType.VAL:
            stack.append(token.value)
            
        elif token.type == TokenType.OP:
            if token.prec == MAX_PREC:
                # Unary operator
                if len(stack) == 0:
                    return None
                operand = stack.pop()
                if token.op_str == "~":
                    result = ~operand
                elif token.op_str == "!":
                    result = 0 if operand else 1
                elif token.op_str == "+":
                    result = operand
                elif token.op_str == "-":
                    result = (-operand)
                else:
                    return None
                stack.append(result)
                
            else:
                # Binary operator
                if len(stack) < 2:
                    return None
                right = stack.pop()
                left = stack.pop()
                if token.op_str == "<<":
                    result = left << right
                elif token.op_str == ">>":
                    result = left >> right
                elif token.op_str == ">=":
                    result = 1 if left >= right else 0
                elif token.op_str == "<=":
                    result = 1 if left <= right else 0
                elif token.op_str == ">":
                    result = 1 if left > right else 0
                elif token.op_str == "<":
                    result = 1 if left < right else 0
                elif token.op_str == "==":
                    result = 1 if left == right else 0
                elif token.op_str == "!=":
                    result = 1 if left != right else 0
                elif token.op_str == "*":
                    result = left * right
                elif token.op_str == "/":
                    if right == 0:
                        return None
                    # Python's // does floor division for negative numbers
                    # We want C-style truncation toward zero
                    if left < 0 and right > 0:
                        result = -((-left) // right)
                    elif left > 0 and right < 0:
                        result = -(left // (-right))
                    else:
                        result = left // right
                elif token.op_str == "%":
                    if right == 0:
                        return None
                    # Python's % returns non-negative remainder
                    # We want C-style remainder (sign matches dividend)
                    result = left % right
                    if left < 0 and result != 0:
                        result -= right
                elif token.op_str == "+":
                    result = left + right
                elif token.op_str == "-":
                    result = left - right
                elif token.op_str == "&":
                    result = left & right
                elif token.op_str == "^":
                    result = left ^ right
                elif token.op_str == "|":
                    result = left | right
                else:
                    return None
                
                stack.append(result)
                
        else:
            return None  # Invalid token type in postfix
    
    if len(stack) != 1:
        return None
    return stack[0]


def trucate_bits(val: int, n_bits: int):
    if n_bits > 0:
        mask = (2 << (n_bits - 1) ) - 1
        return val & mask
    else:
        return val


def format_output(val: int, radix: str):
    if radix in {"x", "hex", "16"}:
        return f"{val:x}"
    elif radix in {"d", "dec", "10"}:
        return f"{val:d}"
    elif radix in {"o", "oct", "8"}:
        return f"{val:o}"
    elif radix in {"b", "bin", "2"}:
        return f"{val:b}"
    else:
        return f"{val:d}"


from .uctool import UCTool
from pydantic import BaseModel, Field
from langchain_core.tools.base import ArgsSchema

class ExpressionArgs(BaseModel):
        expr: str = Field(..., description="The expression to evaluate.")
        radix: str = Field(..., description="The radix of the output, should be one of: bin, oct, dec, hex.")
        n_bits: str = Field(..., description="Truncate the output to n bits. If zero, the output will not be truncated.")

class ExpressionTool(UCTool):
        name: str = "Expression"
        description: str = (
            "Evaluate an expression and output the result in specified format. The expressions are evaluated with signed integers of arbitrary precision.."
            "Numbers can be specified in binary (with the 0b prefix), octal, (with the 0o prefix), decimal (with no prefix) or hexadecimal (with the 0x prefix)."
            "Supported operators (same semantics as C): ~ ! * / % + - >> << > < >= <= == != & | ^"
            "Use parentheses to avoid ambiguity in precedence."
        )
        args_schema: Optional[ArgsSchema] = ExpressionArgs

        def _run(self, expr: str, radix: str, n_bits: str, run_manager=None) -> str:
            try:
                n = int(n_bits)
            except:
                n = 0
            tokens = tokenize_expression(expr)
            for token in tokens:
                if token.type == TokenType.INVALID:
                    return "Tokenization Error"
            parsed_expression = parse_expression(tokens)
            if parsed_expression is None:
                return "Parsing Error"
            value = evaluate_postfix_expression(parsed_expression)
            if value is None:
                return "Evaluation Error"
            return format_output(trucate_bits(value, n), radix)
