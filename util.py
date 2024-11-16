def milliseconds_to_hmsms(milliseconds):
    # 计算小时数
    hours, milliseconds = divmod(milliseconds, 3600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    # 格式化输出
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

if __name__ == "__main__":
    print(milliseconds_to_hmsms(4623430))
