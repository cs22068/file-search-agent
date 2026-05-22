#!/usr/bin/env node

// CDKアプリ起動ファイル、CDKスタックを定義してアプリに追加する
import * as cdk from 'aws-cdk-lib';
import { FileSearchStack } from '../lib/file-search-stack';

const app = new cdk.App();

new FileSearchStack(app, 'FileSearchStack', {
    env: {
        account: process.env.CDK_DEFAULT_ACCOUNT,
        region: 'ap-northeast-1',
    },
    description: 'File Search Agent - Bedrock IAM resources',
});
