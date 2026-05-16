# Troubleshooting

## FileNotFoundError - classes-dex2jar.jar

Newer APKs may fail to be decompiled as part of pbtk. This repository has been updated to use dex2jar 2.4, which should support all APKs. When dex2jar cannot decompile an APK, it will fail to produce the classes-dex2jar.jar file, which will result in a FileNotFoundError.

```bash
DEBUG:root:[i] Converting DEX to JAR...
[...]
FileNotFoundError: [Errno 2] No such file or directory: '/tmp/tmpbha7v_6y/classes-dex2jar.jar'
```

When this error occurs, two things should be checked - whether dex2jar is able to decompile the apk, and whether there is enough java heap space for the decompilation can occur

### Check dex2jar version

Run dex2jar manually on your apk from this repository to confirm that it is not a dex2jar related issue. 

```bash
cd src/utils/external/dex2jar && \
./d2j-dex2jar.sh <apk_file>
```

An indication of an out of date dex2jar looks like this:

```bash
com.googlecode.d2j.DexException: not support version.
        at com.googlecode.d2j.reader.DexFileReader.<init>(DexFileReader.java:151)
        at com.googlecode.d2j.reader.DexFileReader.<init>(DexFileReader.java:211)
        at com.googlecode.dex2jar.tools.Dex2jarCmd.doCommandLine(Dex2jarCmd.java:104)
        at com.googlecode.dex2jar.tools.BaseCmd.doMain(BaseCmd.java:288)
        at com.googlecode.dex2jar.tools.Dex2jarCmd.main(Dex2jarCmd.java:32)
```

If the version of dex2jar is too old, grab the latest version from [pxb1988/dex2jar](https://github.com/pxb1988/dex2jar) and replace the contents of `src/utils/external/dex2jar` with the new version.

### Check Java heap space

If dex2jar fails to run, this could be due to memory issues. By default, dex2jar is configured to use 512M - 2GB of heap space.

This can be adjusted by updating the `-Xmx2048m` value in `src/utils/external/dex2jar/d2j-dex2jar.sh`. For example, to increase it to 4GB, change it to `-Xmx4096m`. Alternatively, set the value via an environment variable:

```bash
export _JAVA_OPTIONS="-Xmx4096m"
```
