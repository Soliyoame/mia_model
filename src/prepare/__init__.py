"""PCV-MIA 数据集切分与攻击基准准备包。

本包负责预处理后续两步:把已处理记录切分成 KB_Member/True_Non_Member 等组(splitter),
再据此构建不可变的攻击基准文件(benchmark_builder)。
"""
